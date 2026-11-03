"""Recovery transaction ownership, whole-database guard and measured rewrite."""
from unittest.mock import patch
from psycopg.errors import LockNotAvailable
from tests.latest_board_fixture import LatestBoardFixture
from app.storage.storage_maintenance import maintain
from app.storage.grid_packet_store import put
from app.collection.current_storage_policy import sql_usage,writer_subset_usage
from app.collection import native_recovery


class StorageMaintenanceSQL(LatestBoardFixture):
    async def test_small_packet_bloat_reclaimed_without_changing_selected_original_or_lease(self):
        from app.storage.grid_packet_store import PacketStore
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            packet=b'live selected Original with exact source clock'
            pinned=put(db,packet)
            db.execute("INSERT INTO current_grid_read_lease VALUES ('small-bloat',now()+interval '1 hour',%s)",([pinned],))
            db.execute("""INSERT INTO current_grid_blob(id,packet)
                SELECT encode(sha256(convert_to('churn-'||i,'UTF8')),'hex'),convert_to((SELECT string_agg(md5(i::text||':'||j::text),'')
                    FROM generate_series(1,4096) j),'UTF8') FROM generate_series(1,70) i""")
            db.execute("DELETE FROM current_grid_blob WHERE id IN (SELECT encode(sha256(convert_to('churn-'||i,'UTF8')),'hex') FROM generate_series(1,70) i)")
            db.execute('VACUUM (TRUNCATE FALSE) current_grid_blob')
            lease=db.execute("SELECT * FROM current_grid_read_lease WHERE token='small-bloat'").fetchone()
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0):result=maintain(db)
            rewrite=next(r for r in result['rewrites'] if r['table']=='current_grid_blob')
            self.assertLess(rewrite['measured_reusable_bytes'],32*1024*1024)
            self.assertGreater(rewrite['before_bytes']-rewrite['after_bytes'],4*1024*1024)
            self.assertEqual(lease,db.execute("SELECT * FROM current_grid_read_lease WHERE token='small-bloat'").fetchone())
            self.assertEqual(packet,PacketStore.from_connection(db).load(pinned))

    async def test_cleanup_commits_despite_later_publication_failure_and_preserves_pinned(self):
        with self.connect() as db:
            expired=put(db,b'expired original')
            pinned=put(db,b'pinned original')
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=ANY(%s)",([expired,pinned],))
            db.execute("INSERT INTO current_grid_read_lease VALUES ('maintenance-test',now()+interval '1 hour',%s)",([pinned],))
            maintain(db,compact=False)
            with self.assertRaises(ValueError),db.transaction():
                db.execute('DELETE FROM current_grid_read_lease')
                raise ValueError('later_publication_capacity_rejection')
            self.assertIsNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(expired,)).fetchone())
            self.assertIsNotNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(pinned,)).fetchone())
            with db.transaction(),self.assertRaisesRegex(ValueError,'independent_transaction'):maintain(db)
            self.assertGreater(sql_usage(db),writer_subset_usage(db))

    async def test_catalog_replacement_reuses_unchanged_rows_and_removes_only_absent(self):
        catalog=dict(events=[],markets=[dict(id='one',event_id='event',title='kept'),dict(id='two',event_id='event')])
        with patch.object(native_recovery,'connect',self.connect):
            native_recovery.save('kalshi','scope',catalog,{})
            with self.connect() as db:before={r['market_id']:r['xmin'] for r in db.execute('SELECT market_id,xmin::text FROM current_native_market_recovery')}
            native_recovery.save('kalshi','scope',catalog,{})
            with self.connect() as db:self.assertEqual(before,{r['market_id']:r['xmin'] for r in db.execute('SELECT market_id,xmin::text FROM current_native_market_recovery')})
            catalog['markets']=catalog['markets'][:1]
            native_recovery.save('kalshi','scope',catalog,{})
            with self.connect() as db:self.assertEqual([r['market_id'] for r in db.execute('SELECT market_id FROM current_native_market_recovery')],['one'])

    async def test_lock_failure_releases_maintenance_owner_and_recovers(self):
        with self.connect() as blocker,self.connect() as db:
            with blocker.transaction():
                blocker.execute('LOCK TABLE current_grid_blob IN ACCESS EXCLUSIVE MODE')
                with self.assertRaises(LockNotAvailable):maintain(db,compact=False)
            result=maintain(db,compact=False)
            self.assertIn('after_bytes',result)
            self.assertEqual(db.execute('SHOW lock_timeout').fetchone()['lock_timeout'],'0')

    async def test_prospective_generation_trace_is_snapshot_bound_and_bounded(self):
        self.reconcile()
        with self.connect() as db:
            traces=db.execute("SELECT trace,admitted_at,completed_at,published_at FROM pipeline_generation WHERE trace<>'{}'::jsonb").fetchall()
        self.assertTrue(traces)
        for row in traces:
            self.assertLessEqual(len(row['trace']['witnesses']),8)
            self.assertTrue(row['trace']['captured_at'])
            self.assertTrue(row['admitted_at'])
            for value in row['trace']['witnesses']:self.assertNotIn('raw',value)

    async def test_measured_compaction_reduces_physical_guard_without_losing_live_rows(self):
        from app.storage.store import hashed
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute("INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES ('kalshi','fixture','{}') ON CONFLICT(source) DO NOTHING")
            db.execute("""INSERT INTO current_native_market_recovery(source,market_id,metadata)
                SELECT 'kalshi','churn-'||i,jsonb_build_object('payload',
                    (SELECT string_agg(md5(i::text||':'||j::text),'') FROM generate_series(1,4096) j))
                FROM generate_series(1,400) i""")
            db.execute("DELETE FROM current_native_market_recovery WHERE market_id LIKE 'churn-%' AND (substring(market_id from 7))::int%20<>0")
            db.execute('VACUUM (TRUNCATE FALSE) current_native_market_recovery')
            before=hashed(db.execute('SELECT source,market_id,metadata,parsed FROM current_native_market_recovery ORDER BY source,market_id').fetchall())
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',sql_usage(db)):
                deferred=maintain(db,collecting=True)
            self.assertFalse(deferred['rewrites'])
            self.assertTrue(any(r['reason']=='rewrite_headroom' for r in deferred['deferred']))
            # Recovery may temporarily cross the operating cap, but preserves
            # the original until commit and reports its separate bounded peak.
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',sql_usage(db)):
                result=maintain(db)
            after=hashed(db.execute('SELECT source,market_id,metadata,parsed FROM current_native_market_recovery ORDER BY source,market_id').fetchall())
            self.assertEqual(before,after)
            self.assertTrue(result['rewrites'])
            self.assertTrue(any(r['transient_peak_bound_bytes']>r['operating_cap_bytes'] for r in result['rewrites']))
            self.assertGreater(result['before_bytes']-result['after_bytes'],32*1024*1024)

    async def test_real_ingress_lock_timeout_advances_then_eventually_recovers(self):
        from app.storage import latest_board as latest
        from app.storage.current_rows import LOCK
        import threading
        held=threading.Event();release=threading.Event();failed=[]
        def block():
            with self.connect() as blocker,blocker.transaction():
                blocker.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
                held.set();release.wait(10)
        thread=threading.Thread(target=block);thread.start();self.assertTrue(held.wait(5))
        original=latest._reconcile
        def real_attempt(db,**kwargs):
            try:return original(db,**kwargs)
            except LockNotAvailable:
                failed.extend(kwargs['event_ids']);release.set();thread.join(5)
                raise
        try:
            with self.connect() as db,patch.object(latest,'_reconcile',side_effect=real_attempt):
                db.execute("SET lock_timeout='100ms'")
                admission={'estimates_window_turn':3}
                first=latest.reconcile(db,at=self.at.isoformat(),admission=admission)
                self.assertTrue(failed)
                self.assertTrue(first['published'])
                self.assertTrue(admission.get('estimates_rotation_after'))
                reasons=db.execute("SELECT reason FROM current_pipeline_attempt WHERE event_id=ANY(%s) AND branch='metrics'",(failed,)).fetchall()
                self.assertTrue(any(r['reason']=='attempt_LockNotAvailable' for r in reasons))
                latest.reconcile(db,at=self.at.isoformat(),admission=admission)
                self.assertTrue(db.execute('SELECT 1 FROM latest_board WHERE publication_events ?| %s',(failed,)).fetchone())
        finally:release.set();thread.join(5)

    async def test_admitted_capture_expansion_rotates_and_later_publishes(self):
        from app.storage import latest_board as latest
        original=latest._reconcile;deferred=[]
        def expanded(db,**kwargs):
            if not deferred:
                deferred.extend(kwargs['event_ids'])
                kwargs['reservation_bytes']=1
            return original(db,**kwargs)
        with self.connect() as db,patch.object(latest,'_reconcile',side_effect=expanded):
            admission={'estimates_window_turn':3}
            first=latest.reconcile(db,at=self.at.isoformat(),admission=admission)
            self.assertTrue(first['published'])
            self.assertTrue(admission.get('estimates_rotation_after'))
            self.assertTrue(any(e['reason']=='background_capture_changed' for e in first['errors']))
            latest.reconcile(db,at=self.at.isoformat(),admission=admission)
            self.assertTrue(db.execute('SELECT 1 FROM latest_board WHERE publication_events ?| %s',(deferred,)).fetchone())

    async def test_cleanup_cannot_delete_packet_while_reader_is_creating_lease(self):
        from app.storage.grid_packet_store import cleanup
        with self.connect() as db,self.connect() as reader:
            packet=put(db,b'concurrent-pinned-evidence')
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=%s",(packet,))
            with reader.transaction():
                reader.execute('SELECT id FROM current_grid_blob WHERE id=%s FOR KEY SHARE',(packet,))
                # Cleanup skips a packet owned by an in-progress pin transaction.
                cleanup(db)
                self.assertIsNotNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(packet,)).fetchone())
                reader.execute("INSERT INTO current_grid_read_lease VALUES ('concurrent-pin',now()+interval '1 minute',%s)",([packet],))
            cleanup(db)
            self.assertIsNotNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(packet,)).fetchone())
            db.execute("DELETE FROM current_grid_read_lease WHERE token='concurrent-pin'")
            cleanup(db)
            self.assertIsNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(packet,)).fetchone())

    async def test_locked_rewrite_does_not_starve_other_reclaimable_tables(self):
        with self.connect() as db,self.connect() as blocker:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            for name in ('maintenance_a','maintenance_b'):
                db.execute(f'CREATE TABLE {name}(id integer, payload text)')
                db.execute(f"INSERT INTO {name} SELECT i,(SELECT string_agg(md5(i::text||j::text),'') FROM generate_series(1,4096) j) FROM generate_series(1,300) i")
                db.execute(f'DELETE FROM {name} WHERE id>1')
                db.execute(f'VACUUM (TRUNCATE FALSE) {name}')
            with blocker.transaction():
                blocker.execute('LOCK TABLE maintenance_a IN ACCESS SHARE MODE')
                with patch('app.storage.storage_maintenance.COMPACT_TABLES',('maintenance_a','maintenance_b')),patch('app.storage.storage_maintenance.PRESSURE_BYTES',0):
                    result=maintain(db)
            self.assertIn(dict(table='maintenance_a',reason='lock_timeout'),result['deferred'])
            self.assertIn('maintenance_b',[r['table'] for r in result['rewrites']])
            self.assertEqual(db.execute('SELECT count(*) n FROM maintenance_a').fetchone()['n'],1)
            self.assertEqual(db.execute('SELECT count(*) n FROM maintenance_b').fetchone()['n'],1)

    async def test_expiry_lock_failure_still_runs_independent_retention(self):
        from types import SimpleNamespace
        from app.collection.current_database import DatabasePipeline
        from app.storage.current_rows import LOCK
        pipeline=DatabasePipeline(SimpleNamespace())
        with self.connect() as db,self.connect() as blocker:
            packet=put(db,b'expired despite expiry contention')
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=%s",(packet,))
            with blocker.transaction():
                blocker.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
                def connection():
                    connection=self.connect()
                    connection.execute("SET lock_timeout='100ms'")
                    return connection
                with patch('app.collection.current_database.connect',side_effect=connection),self.assertRaises(LockNotAvailable):
                    pipeline.tick()
            self.assertIsNotNone(pipeline.maintenance)
            self.assertIsNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(packet,)).fetchone())
