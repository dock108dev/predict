"""Recovery transaction ownership, whole-database guard and measured rewrite."""
from unittest.mock import patch
from psycopg.errors import LockNotAvailable
from tests.latest_board_fixture import LatestBoardFixture
from app.storage.storage_maintenance import maintain
from app.storage.grid_packet_store import put
from app.collection.current_storage_policy import sql_usage,writer_subset_usage
from app.collection import native_recovery


class StorageMaintenanceSQL(LatestBoardFixture):
    async def test_partitioning_does_not_multiply_the_logical_reclaim_threshold(self):
        import os
        from psycopg.types.json import Jsonb
        from app.storage import storage_maintenance as maintenance
        with self.connect()as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute('TRUNCATE current_acquisition_image_parts')
            with db.cursor()as cursor:
                cursor.executemany('INSERT INTO current_acquisition_image_parts(source,event_id,market_id,received_at,disposition,image) VALUES(%s,%s,%s,now(),%s,%s)',
                    [('kalshi','bounded-copy',str(n),'pending',Jsonb(dict(raw=os.urandom(16384).hex())))for n in range(1024)])
            db.execute('DELETE FROM current_acquisition_image_parts WHERE market_id::integer%4<>0')
            db.execute('VACUUM (TRUNCATE FALSE) current_acquisition_image_parts')
            before=db.execute("SELECT market_id,image FROM current_acquisition_image_parts ORDER BY market_id").fetchall()
            parts=db.execute("SELECT relid,pg_total_relation_size(relid) bytes FROM pg_partition_tree('current_acquisition_image_parts') WHERE isleaf").fetchall()
            self.assertLess(max(r['bytes']for r in parts),maintenance.MIN_REUSABLE_BYTES)
            with patch.object(maintenance,'PRESSURE_BYTES',0),patch.object(maintenance,'COMPACT_TABLES',('current_acquisition_image_parts',)),patch.object(maintenance,'REWRITE_TURN_SECONDS',0):
                result=maintain(db,collecting=True)
            self.assertEqual(len(result['rewrites']),1)
            rewrite=result['rewrites'][0]
            self.assertEqual(rewrite['minimum_reclaim_bytes'],maintenance.MIN_REUSABLE_BYTES//16)
            self.assertGreater(rewrite['before_bytes']-rewrite['after_bytes'],rewrite['minimum_reclaim_bytes'])
            self.assertEqual(before,db.execute('SELECT market_id,image FROM current_acquisition_image_parts ORDER BY market_id').fetchall())

    async def test_old_reader_retained_tuples_do_not_become_an_irreducible_floor(self):
        from app.storage import storage_maintenance as maintenance
        with self.connect() as db,self.connect() as reader:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute('CREATE TABLE maintenance_reader_fixture(id integer PRIMARY KEY,payload text)')
            db.execute("INSERT INTO maintenance_reader_fixture SELECT n,repeat('complete retained value ',14) FROM generate_series(1,6000)n")
            maintenance._rewrite_floor.clear()
            with patch.object(maintenance,'PRESSURE_BYTES',0),patch.object(maintenance,'MIN_REUSABLE_BYTES',128*1024),patch.object(maintenance,'COMPACT_TABLES',('maintenance_reader_fixture',)):
                with reader.transaction():
                    reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    reader.execute('SELECT * FROM current_row_epoch').fetchall()
                    db.execute('DELETE FROM maintenance_reader_fixture WHERE id>1000')
                    first=maintain(db,collecting=True)
                    self.assertEqual(len(first['rewrites']),1)
                db.execute('VACUUM (TRUNCATE FALSE) maintenance_reader_fixture')
                second=maintain(db,collecting=True)
                self.assertEqual(len(second['rewrites']),1)
                self.assertGreater(second['rewrites'][0]['before_bytes']-second['rewrites'][0]['after_bytes'],128*1024)
                self.assertEqual(db.execute('SELECT count(*) n FROM maintenance_reader_fixture').fetchone()['n'],1000)
            db.execute('DROP TABLE maintenance_reader_fixture')

    async def test_irreducible_page_slack_is_not_rewritten_until_new_reclaimable_growth(self):
        from app.storage import storage_maintenance as maintenance
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute('CREATE TABLE maintenance_rewrite_fixture(id integer PRIMARY KEY,payload text) WITH(fillfactor=50)')
            db.execute("INSERT INTO maintenance_rewrite_fixture SELECT n,repeat('complete retained value ',14) FROM generate_series(1,6000)n")
            before=db.execute('SELECT * FROM maintenance_rewrite_fixture ORDER BY id').fetchall()
            maintenance._rewrite_floor.clear()
            with patch.object(maintenance,'PRESSURE_BYTES',0),patch.object(maintenance,'MIN_REUSABLE_BYTES',128*1024),patch.object(maintenance,'COMPACT_TABLES',('maintenance_rewrite_fixture',)):
                first=maintain(db,collecting=True)
                self.assertEqual(len(first['rewrites']),1)
                second=maintain(db,collecting=True)
                self.assertEqual(second['rewrites'],[])
                self.assertIn('maintenance_rewrite_fixture',second['unchanged_rewrite_floor'])
                self.assertEqual(before,db.execute('SELECT * FROM maintenance_rewrite_fixture ORDER BY id').fetchall())
                # A real removal creates newly reclaimable pages and must regain
                # service even though the relation has the same identity.
                db.execute('DELETE FROM maintenance_rewrite_fixture WHERE id>1000')
                db.execute('VACUUM (TRUNCATE FALSE) maintenance_rewrite_fixture')
                third=maintain(db,collecting=True)
                self.assertEqual(len(third['rewrites']),1)
                self.assertGreater(third['rewrites'][0]['before_bytes']-third['rewrites'][0]['after_bytes'],128*1024)
                self.assertEqual(before[:1000],db.execute('SELECT * FROM maintenance_rewrite_fixture ORDER BY id').fetchall())
            db.execute('DROP TABLE maintenance_rewrite_fixture')

    async def test_acquisition_partition_upgrade_preserves_original_clocks_and_generated_values(self):
        from pathlib import Path
        from psycopg.types.json import Jsonb
        with self.connect() as db,db.transaction(force_rollback=True):
            db.execute('DROP VIEW current_acquisition_image')
            db.execute('ALTER TABLE current_acquisition_image_parts RENAME TO current_acquisition_image')
            db.execute('ALTER TABLE current_acquisition_image DROP COLUMN depth_payload,DROP COLUMN wire_payload')
            for table in ('current_acquisition_image','current_acquisition_market'):
                db.execute(f'CREATE TEMP TABLE shape_{table} (LIKE {table} INCLUDING ALL)')
                db.execute(f'DROP TABLE {table}')
                db.execute(f'CREATE TABLE {table} (LIKE shape_{table} INCLUDING ALL)')
            image=dict(original='完整 provider text',source_at='2026-11-04T11:59:00Z',
                outcomes=[dict(price='0.1234567890123456789',quantity='9007199254740993.00001')])
            for mid,clock in (('one','2026-11-04T12:00:05Z'),('two',None)):
                db.execute('INSERT INTO current_acquisition_image(source,event_id,market_id,received_at,disposition,image,runtime_id,connection_generation,census_generation,persisted_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    ('kalshi','event',mid,'2026-11-04T12:00:00Z','rejected',Jsonb(image),'original-runtime',7,'exact-census',clock))
            db.execute('INSERT INTO current_acquisition_market(source,event_id,market_id,sport,family,generation,observed_at,withdrawn,disposition,metadata,absent_since,missing_passes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                ('kalshi','event','one','NFL','spread','original-census','2026-11-04T12:00:00Z',False,'suspected_absent',Jsonb(dict(title='original',line='2.5')),'2026-11-04T11:00:00Z',3))
            before={table:db.execute(f'SELECT * FROM {table} ORDER BY source,event_id,market_id').fetchall() for table in ('current_acquisition_image','current_acquisition_market')}
            migration=(Path(__file__).resolve().parents[1]/'app/storage/migrations/062_acquisition_evidence_partitions.sql').read_text()
            with db.transaction():db.execute(migration)
            for table,rows in before.items():
                self.assertEqual(rows,db.execute(f'SELECT * FROM {table} ORDER BY source,event_id,market_id').fetchall())
                self.assertEqual(db.execute('SELECT count(*) n FROM pg_partition_tree(%s::regclass) WHERE isleaf',(table,)).fetchone()['n'],16)
            db.execute("UPDATE current_acquisition_image SET disposition='admitted' WHERE market_id='one'")
            old=before['current_acquisition_image'][0]['persisted_at']
            self.assertEqual(db.execute("SELECT persisted_at FROM current_acquisition_image WHERE market_id='one'").fetchone()['persisted_at'],old)
            db.execute("UPDATE current_acquisition_image SET received_at=now() WHERE market_id='one'")
            self.assertGreater(db.execute("SELECT persisted_at FROM current_acquisition_image WHERE market_id='one'").fetchone()['persisted_at'],old)

    async def test_raw_image_partition_reclaims_inside_bounded_copy_runway(self):
        from app.storage.storage_maintenance import REWRITE_RUNWAY_BYTES
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute("""INSERT INTO current_acquisition_image_parts(source,event_id,market_id,received_at,disposition,image)
                SELECT 'kalshi','partition-proof','image-'||i,now(),'pending',jsonb_build_object('payload',
                    (SELECT string_agg(md5(i::text||':'||j::text),'') FROM generate_series(1,4096) j))
                FROM generate_series(1,400) i""")
            db.execute("DELETE FROM current_acquisition_image_parts WHERE event_id='partition-proof' AND (substring(market_id from 7))::int%20<>0")
            db.execute('VACUUM (TRUNCATE FALSE) current_acquisition_image_parts')
            sizes=[r['bytes']for r in db.execute("SELECT pg_total_relation_size(relid) bytes FROM pg_partition_tree('current_acquisition_image_parts') WHERE isleaf")]
            before=sql_usage(db);cap=before+max(sizes)+REWRITE_RUNWAY_BYTES+1
            self.assertGreater(before+sum(sizes)+REWRITE_RUNWAY_BYTES,cap)
            # Isolate the FULL-copy runway: ordinary hot-table VACUUM can
            # already truncate empty partitions before this assertion on PG14.
            with patch('app.storage.storage_maintenance.HOT_TABLES',()),patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',cap),patch('app.storage.storage_maintenance.MIN_REUSABLE_BYTES',128*1024),patch('app.storage.storage_maintenance.COMPACT_TABLES',('current_acquisition_image_parts',)),patch('app.storage.storage_maintenance.REWRITE_TURN_SECONDS',0):
                result=maintain(db,collecting=True)
            self.assertEqual(len(result['rewrites']),1,result)
            rewrite=result['rewrites'][0]
            self.assertTrue(rewrite['table'].startswith('current_acquisition_image_p'))
            self.assertLess(rewrite['transient_peak_bound_bytes'],cap)
            self.assertGreater(rewrite['before_bytes']-rewrite['after_bytes'],128*1024)
            self.assertEqual(db.execute("SELECT count(*) n FROM current_acquisition_image_parts WHERE event_id='partition-proof'").fetchone()['n'],20)

    async def test_bounded_recovery_repack_preserves_exact_records_and_skips_locked(self):
        from psycopg.types.json import Jsonb
        from app.storage import recovery_codec as codec
        original=dict(title='exact',period='full_game',sides=[],payload='original evidence '*1000,
            raw=dict(received_at='2026-11-04T00:00:00Z',number=10**80))
        with self.connect() as db,self.connect() as writer:
            db.execute('DELETE FROM current_native_market_recovery')
            db.execute('DELETE FROM current_native_catalog_recovery')
            db.execute("INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES('kalshi','scope','{}')")
            for key in ('a','b','c'):
                db.execute('INSERT INTO current_native_market_recovery(source,market_id,metadata,parsed) VALUES(%s,%s,%s,%s)',
                    ('kalshi',key,Jsonb(original),Jsonb(original)))
            header=db.execute('SELECT * FROM current_native_catalog_recovery').fetchall()
            codec._after.clear()
            with writer.transaction():
                writer.execute("SELECT 1 FROM current_native_market_recovery WHERE market_id='a' FOR UPDATE")
                with patch.object(codec,'REPACK_ROWS',2):first=codec.repack(db)
                self.assertEqual(first['updated'],1)
                self.assertEqual(codec.repack(db)['updated'],1)
            codec.repack(db)  # wrap after the bounded scan
            self.assertEqual(codec.repack(db)['updated'],1)
            before=db.execute('SELECT market_id,xmin::text FROM current_native_market_recovery ORDER BY market_id').fetchall()
            codec.repack(db);codec.repack(db)
            self.assertEqual(before,db.execute('SELECT market_id,xmin::text FROM current_native_market_recovery ORDER BY market_id').fetchall())
            self.assertEqual(header,db.execute('SELECT * FROM current_native_catalog_recovery').fetchall())
            for row in db.execute('SELECT metadata,parsed FROM current_native_market_recovery'):
                self.assertEqual(codec.thaw(row['metadata']),original)
                self.assertEqual(codec.thaw(row['parsed']),original)
            with patch('app.collection.current_storage_policy.sql_usage',return_value=2**31):
                self.assertEqual(codec.repack(db)['deferred'],'recovery_repack_headroom')

    async def test_repack_batch_bounds_exact_source_pairs_and_raw_bytes(self):
        from psycopg.types.json import Jsonb
        from app.storage import recovery_codec as codec
        original=dict(title='exact',payload='complete evidence '*4000)
        with self.connect() as db:
            db.execute('DELETE FROM current_native_market_recovery')
            db.execute('DELETE FROM current_native_catalog_recovery')
            for source in ('kalshi','polymarket_us'):
                db.execute('INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES(%s,%s,%s)',(source,'scope',Jsonb({})))
            for source,mid in (('kalshi','z'),('polymarket_us','a'),('polymarket_us','z')):
                db.execute('INSERT INTO current_native_market_recovery(source,market_id,metadata) VALUES(%s,%s,%s)',(source,mid,Jsonb(original)))
            codec._after.clear()
            with patch.object(codec,'REPACK_ROWS',2),patch.object(codec,'REPACK_BYTES',100000):
                first=codec.repack(db)
                self.assertEqual(first['updated'],1)
                self.assertLessEqual(first['output_bytes'],100000)
                packed=db.execute("SELECT source,market_id FROM current_native_market_recovery WHERE metadata ? '_predict_storage'").fetchall()
                self.assertEqual(packed,[dict(source='kalshi',market_id='z')])
                self.assertEqual(codec.repack(db)['updated'],1)
                self.assertEqual(codec.repack(db)['updated'],1)
            for row in db.execute('SELECT metadata FROM current_native_market_recovery'):
                self.assertEqual(codec.thaw(row['metadata']),original)

    async def test_noop_bloat_scan_does_not_request_publication_lock(self):
        from app.storage import storage_maintenance as maintenance
        with self.connect() as db,self.connect() as publisher:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute('CREATE TABLE dense_scan_fixture(id integer)')
            db.execute('INSERT INTO dense_scan_fixture SELECT generate_series(1,10)')
            publisher.execute('SELECT pg_advisory_lock(901153)')
            try:
                with patch.object(maintenance,'PRESSURE_BYTES',0),patch.object(maintenance,'COMPACT_TABLES',('dense_scan_fixture',)),patch.object(maintenance,'CAPTURE_WAIT_SECONDS',.001):
                    result=maintain(db,collecting=True)
                self.assertFalse(result['capture_lock_acquired'])
                self.assertNotIn('capture_lock_wait_seconds',result)
                self.assertNotEqual(result.get('state'),'busy')
                self.assertEqual(result['rewrites'],[])
                self.assertEqual(db.execute('SELECT count(*) n FROM dense_scan_fixture').fetchone()['n'],10)
            finally:
                publisher.execute('SELECT pg_advisory_unlock_all()')
                db.execute('DROP TABLE dense_scan_fixture')

    async def test_live_reclamation_waits_for_publication_and_yields_after_one_rewrite(self):
        import threading
        with self.connect() as db,self.connect() as publisher:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            for name in ('staged_a','staged_b'):
                db.execute(f'CREATE TABLE {name}(id integer,payload text)')
                db.execute(f"INSERT INTO {name} SELECT i,(SELECT string_agg(md5(i::text||j::text),'') FROM generate_series(1,4096) j) FROM generate_series(1,70) i")
                db.execute(f'DELETE FROM {name} WHERE id>1')
                db.execute(f'VACUUM (TRUNCATE FALSE) {name}')
            publisher.execute('SELECT pg_advisory_lock(901153)')
            release=threading.Timer(.25,lambda:publisher.execute('SELECT pg_advisory_unlock(901153)'))
            release.start()
            try:
                with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.COMPACT_TABLES',('staged_a','staged_b')),patch('app.storage.storage_maintenance.REWRITE_TURN_SECONDS',0):
                    from app.storage import recovery_codec
                    original_repack=recovery_codec.repack
                    def independent_repack(connection):
                        # Post-rewrite work must release the publication owner.
                        self.assertTrue(publisher.execute('SELECT pg_try_advisory_lock(901153) held').fetchone()['held'])
                        publisher.execute('SELECT pg_advisory_unlock(901153)')
                        return original_repack(connection)
                    with patch.object(recovery_codec,'repack',side_effect=independent_repack):
                        first=maintain(db,collecting=True)
                    self.assertTrue(first['capture_lock_acquired'])
                    self.assertEqual(len(first['rewrites']),1)
                    self.assertTrue(first['continue_compaction'])
                    self.assertTrue(publisher.execute('SELECT pg_try_advisory_lock(901153) held').fetchone()['held'])
                    publisher.execute('SELECT pg_advisory_unlock(901153)')
                    second=maintain(db,collecting=True)
                    self.assertEqual(len(second['rewrites']),1)
                    self.assertNotEqual(first['rewrites'][0]['table'],second['rewrites'][0]['table'])
                    for name in ('staged_a','staged_b'):
                        self.assertEqual(db.execute(f'SELECT id FROM {name}').fetchall(),[dict(id=1)])
            finally:
                release.join();publisher.execute('SELECT pg_advisory_unlock_all()')

    async def test_small_packet_bloat_reclaimed_without_changing_selected_original_or_lease(self):
        from app.storage.grid_packet_store import PacketStore
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            # A statement-level TRUNCATE FALSE does not govern a concurrent
            # autovacuum. Retain this fixture's empty heap/TOAST pages until
            # maintenance gets its turn, even on a slow shared CI runner.
            db.execute('ALTER TABLE current_grid_blob SET (vacuum_truncate=false,toast.vacuum_truncate=false)')
            try:
                packet=b'live selected Original with exact source clock'
                pinned=put(db,packet)
                db.execute("INSERT INTO current_grid_read_lease VALUES ('small-bloat',now()+interval '1 hour',%s)",([pinned],))
                db.execute("""INSERT INTO current_grid_blob(id,packet)
                    SELECT encode(sha256(convert_to('churn-'||i,'UTF8')),'hex'),convert_to((SELECT string_agg(md5(i::text||':'||j::text),'')
                        FROM generate_series(1,4096) j),'UTF8') FROM generate_series(1,70) i""")
                db.execute("DELETE FROM current_grid_blob WHERE id IN (SELECT encode(sha256(convert_to('churn-'||i,'UTF8')),'hex') FROM generate_series(1,70) i)")
                # An ordinary vacuum uses the same relation options as the
                # background worker; reusable pages must remain for the rewrite.
                db.execute('VACUUM current_grid_blob')
                reusable=db.execute("""SELECT sum(s.free_space+s.dead_tuple_len) n
                    FROM pg_class c CROSS JOIN LATERAL pgstattuple(c.oid) s
                    WHERE c.oid='current_grid_blob'::regclass
                       OR c.oid=(SELECT reltoastrelid FROM pg_class WHERE oid='current_grid_blob'::regclass)""").fetchone()['n']
                self.assertGreater(reusable,4*1024*1024,'Fixture must retain measurable bloat before maintenance')
                lease=db.execute("SELECT * FROM current_grid_read_lease WHERE token='small-bloat'").fetchone()
                with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0):result=maintain(db)
                rewrites={r['table']:r for r in result['rewrites']}
                self.assertIn('current_grid_blob',rewrites,result)
                rewrite=rewrites['current_grid_blob']
                self.assertLess(rewrite['measured_reusable_bytes'],32*1024*1024)
                self.assertGreater(rewrite['before_bytes']-rewrite['after_bytes'],4*1024*1024)
                self.assertEqual(lease,db.execute("SELECT * FROM current_grid_read_lease WHERE token='small-bloat'").fetchone())
                self.assertEqual(packet,PacketStore.from_connection(db).load(pinned))
            finally:
                db.execute('ALTER TABLE current_grid_blob RESET (vacuum_truncate,toast.vacuum_truncate)')

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
            from app.storage.recovery_codec import thaw
            def semantic_records():
                return [dict(row,metadata=thaw(row['metadata']),parsed=thaw(row['parsed'])) for row in db.execute(
                    'SELECT source,market_id,metadata,parsed FROM current_native_market_recovery ORDER BY source,market_id')]
            before=hashed(semantic_records())
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.MIN_REUSABLE_BYTES',128*1024),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',sql_usage(db)):
                deferred=maintain(db,collecting=True)
            self.assertFalse(deferred['rewrites'])
            self.assertTrue(any(r['reason']=='rewrite_headroom' for r in deferred['deferred']))
            # Recovery may temporarily cross the operating cap, but preserves
            # the original until commit and reports its separate bounded peak.
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.MIN_REUSABLE_BYTES',128*1024),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',sql_usage(db)):
                result=maintain(db)
            after=hashed(semantic_records())
            self.assertEqual(before,after)
            self.assertTrue(result['rewrites'])
            self.assertTrue(any(r['transient_peak_bound_bytes']>r['operating_cap_bytes'] for r in result['rewrites']))
            self.assertGreater(result['before_bytes']-result['after_bytes'],32*1024*1024)

    async def test_partition_reclamation_fits_runway_that_cannot_copy_whole_recovery(self):
        from app.storage.storage_maintenance import REWRITE_RUNWAY_BYTES
        with self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            db.execute("INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES('polymarket_us','partition-proof','{}') ON CONFLICT(source) DO NOTHING")
            db.execute("""INSERT INTO current_native_market_recovery(source,market_id,metadata)
                SELECT 'polymarket_us','partition-'||i,jsonb_build_object('payload',
                    (SELECT string_agg(md5(i::text||':'||j::text),'') FROM generate_series(1,4096) j))
                FROM generate_series(1,400) i""")
            db.execute("DELETE FROM current_native_market_recovery WHERE market_id LIKE 'partition-%' AND (substring(market_id from 11))::int%20<>0")
            db.execute('VACUUM (TRUNCATE FALSE) current_native_market_recovery')
            sizes=[r['bytes'] for r in db.execute("SELECT pg_total_relation_size(relid) bytes FROM pg_partition_tree('current_native_market_recovery') WHERE isleaf")]
            before=sql_usage(db);cap=before+max(sizes)+REWRITE_RUNWAY_BYTES+1
            self.assertGreater(before+sum(sizes)+REWRITE_RUNWAY_BYTES,cap)
            with patch('app.storage.storage_maintenance.PRESSURE_BYTES',0),patch('app.storage.storage_maintenance.SQL_BYTE_CAP',cap),patch('app.storage.storage_maintenance.MIN_REUSABLE_BYTES',128*1024),patch('app.storage.storage_maintenance.COMPACT_TABLES',('current_native_market_recovery',)),patch('app.storage.storage_maintenance.REWRITE_TURN_SECONDS',0):
                result=maintain(db,collecting=True)
            self.assertEqual(len(result['rewrites']),1)
            rewrite=result['rewrites'][0]
            self.assertTrue(rewrite['table'].startswith('current_native_market_recovery_p'))
            self.assertLess(rewrite['transient_peak_bound_bytes'],cap)
            self.assertGreater(rewrite['before_bytes']-rewrite['after_bytes'],128*1024)
            self.assertEqual(db.execute("SELECT count(*) n FROM current_native_market_recovery WHERE market_id LIKE 'partition-%'").fetchone()['n'],20)

    async def test_partition_upgrade_is_exact_atomic_and_refuses_unknown_dependents(self):
        from pathlib import Path
        from psycopg.types.json import Jsonb
        from psycopg.errors import DependentObjectsStillExist
        with self.connect() as db,db.transaction(force_rollback=True):
            db.execute('ALTER TABLE current_native_market_recovery DROP COLUMN receipt_fields')
            db.execute('DELETE FROM current_native_market_recovery')
            db.execute('CREATE TEMP TABLE legacy_recovery_shape (LIKE current_native_market_recovery INCLUDING ALL)')
            db.execute('DROP TABLE current_native_market_recovery')
            db.execute('CREATE TABLE current_native_market_recovery (LIKE legacy_recovery_shape INCLUDING ALL)')
            original=dict(title='original',period='full_game',sides=[dict(id='yes')],large='exact source text '*400,
                receipt='2026-11-04T00:00:00Z',number=10**70)
            db.execute('INSERT INTO current_native_market_recovery(source,market_id,metadata,parsed) VALUES(%s,%s,%s,%s)',('kalshi','upgrade-proof',Jsonb(original),Jsonb(original)))
            before=db.execute('SELECT * FROM current_native_market_recovery').fetchall()
            db.execute('CREATE TABLE unexpected_recovery_owner(source text,market_id text,FOREIGN KEY(source,market_id) REFERENCES current_native_market_recovery(source,market_id))')
            db.execute("INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES('kalshi','upgrade','{}') ON CONFLICT(source) DO NOTHING")
            migration=(Path(__file__).resolve().parents[1]/'app/storage/migrations/061_native_recovery_partitions.sql').read_text()
            with self.assertRaises(DependentObjectsStillExist),db.transaction():db.execute(migration)
            self.assertEqual(before,db.execute('SELECT * FROM current_native_market_recovery').fetchall())
            db.execute('DROP TABLE unexpected_recovery_owner')
            db.execute("INSERT INTO current_native_catalog_recovery(source,scope,header) VALUES('kalshi','upgrade','{}') ON CONFLICT(source) DO NOTHING")
            with db.transaction():db.execute(migration)
            self.assertEqual(before,db.execute('SELECT * FROM current_native_market_recovery').fetchall())
            self.assertEqual(db.execute("SELECT count(*) n FROM pg_partition_tree('current_native_market_recovery') WHERE isleaf").fetchone()['n'],16)

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


class WorkingPartitionUpgradeSQL(LatestBoardFixture):
    def admit(self,records):
        # Seed the historical ranked schema independently of today's writer.
        from app.storage.current_rows import CurrentRowStore
        with patch.object(CurrentRowStore,'replace_native_books'):
            super().admit(records)
        with self.connect() as db:
            c=db.execute("SELECT * FROM current_contract WHERE venue='kalshi' LIMIT 1").fetchone()
            if c:
                db.execute("INSERT INTO current_native_book VALUES(%s,%s,%s,NULL,NULL,%s,1,'fixture-revision','contracts','open','synchronized',NULL,'[]',NULL,NULL)",
                    (c['venue'],c['event_id'],c['native_market_id'],self.at.isoformat()))
                db.execute("INSERT INTO current_native_depth VALUES(%s,%s,%s,%s,'asks',0,'0.37','usd_per_contract','9007199254740993.000001','contracts')",
                    (c['venue'],c['event_id'],c['native_market_id'],c['native_outcome_id']))

    @classmethod
    def setUpClass(cls):
        from hashlib import sha256
        from pathlib import Path
        from app.storage.store import Store
        def legacy(store):
            with store.db.transaction():
                store.db.execute('CREATE TABLE schema_migration(version text PRIMARY KEY,sha256 text NOT NULL)')
                for path in sorted((Path(__file__).resolve().parents[1]/'app/storage/migrations').glob('*.sql')):
                    if path.name>='063_':break
                    store.db.execute(path.read_text())
                    store.db.execute('INSERT INTO schema_migration VALUES(%s,%s)',(path.name,sha256(path.read_bytes()).hexdigest()))
        with patch.object(Store,'migrate',legacy):super().setUpClass()

    async def test_exact_populated_cutover_preserves_pins_triggers_foreign_keys_and_atomic_refusal(self):
        from psycopg.errors import DependentObjectsStillExist,RaiseException
        from app.storage.store import Store
        from app.storage import ordinary_publication as live,comparison_snapshot as snapshots
        order=dict(current_contract='id',current_offer='contract_id',
            current_native_depth='venue,event_id,native_market_id,native_outcome_id,side,level',
            comparison_snapshot='id',comparison_snapshot_result='id',comparison_live_read_fragment='member_id',
            comparison_live_head='singleton',comparison_live_component='id',comparison_live_member='result_id,member_id',
            comparison_live_lease='id')
        with self.connect() as db,patch.object(live,'utc',lambda:self.at.isoformat()),patch.object(snapshots,'utc',lambda:self.at.isoformat()):
            # Seed a pre-063 publication. Delivery diagnostics and stored fee
            # schedules arrived in 069 and 070. Keep the historical schema and
            # use the real snapshot, fragment and lease paths.
            with (
                patch('app.storage.delivery_clocks.captured'),
                patch('app.storage.delivery_clocks.published'),
                patch.object(live.schedule_lifecycle, 'read', return_value=None),
                patch.object(live.product_schedules, 'read_all', return_value={}),
            ):
                live.turn(db)
            head=live.status(db)
            root=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(head['result_id'],)).fetchone()['result'],db=db)
            member=root['rows'][0]['evidence_result_id'];token=live.retain(db,member)
            before={table:db.execute('SELECT * FROM '+table+' ORDER BY '+keys).fetchall()for table,keys in order.items()}
            db.execute('CREATE TABLE unknown_working_reference(id text REFERENCES comparison_snapshot_result(id))')
            with self.assertRaisesRegex(RaiseException,'unknown_foreign_dependency'):Store(db).migrate()
            db.execute('DROP TABLE unknown_working_reference')
            db.execute('CREATE VIEW unknown_working_dependent AS SELECT id FROM current_contract')
            with self.assertRaises(DependentObjectsStillExist):Store(db).migrate()
            self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='current_contract'::regclass").fetchone()['relkind'],'r')
            for table,rows in before.items():self.assertEqual(rows,db.execute('SELECT * FROM '+table+' ORDER BY '+order[table]).fetchall())
            db.execute('DROP VIEW unknown_working_dependent')
            with self.assertRaisesRegex(ValueError,'unknown migration boundary'):Store(db).migrate(through='invented')
            Store(db).migrate(through='063_contract_offer_partitions.sql')
            self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='current_contract'::regclass").fetchone()['relkind'],'p')
            self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='current_native_depth'::regclass").fetchone()['relkind'],'r')
            Store(db).migrate(through='064_native_depth_partitions.sql')
            self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='comparison_snapshot_result'::regclass").fetchone()['relkind'],'r')
            Store(db).migrate(through='065_immutable_publication_partitions.sql')
            for table,rows in before.items():self.assertEqual(rows,db.execute('SELECT * FROM '+table+' ORDER BY '+order[table]).fetchall())
            for table in tuple(order)[:6]:
                self.assertEqual(db.execute('SELECT count(*) n FROM pg_partition_tree(%s::regclass) WHERE isleaf',(table,)).fetchone()['n'],16)
            self.assertEqual(root,snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(head['result_id'],)).fetchone()['result'],db=db))
            with db.transaction(force_rollback=True):
                contract=before['current_contract'][0]
                db.execute("UPDATE current_contract SET facts=facts||'{\"rule_note\":\"changed original rule\"}' WHERE id=%s",(contract['id'],))
                self.assertNotEqual(contract['contract_dependency'],db.execute('SELECT contract_dependency FROM current_contract WHERE id=%s',(contract['id'],)).fetchone()['contract_dependency'])
                offer=before['current_offer'][0]
                db.execute("UPDATE current_offer SET facts=jsonb_set(facts,'{original,value}','\"0.37\"') WHERE contract_id=%s",(offer['contract_id'],))
                self.assertNotEqual(offer['price_dependency'],db.execute('SELECT price_dependency FROM current_offer WHERE contract_id=%s',(offer['contract_id'],)).fetchone()['price_dependency'])
                db.execute('DELETE FROM current_event')
                for table in ('current_contract','current_offer','current_native_depth'):
                    self.assertEqual(db.execute('SELECT count(*) n FROM '+table).fetchone()['n'],0)
            Store(db).migrate(through='066_native_ladders.sql')
            self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='current_native_depth'::regclass").fetchone()['relkind'],'v')
            self.assertEqual(db.execute("SELECT count(*) n FROM pg_partition_tree('current_native_ladder') WHERE isleaf").fetchone()['n'],16)
            self.assertEqual(before['current_native_depth'],db.execute('SELECT * FROM current_native_depth ORDER BY '+order['current_native_depth']).fetchall())
            self.assertEqual(before['comparison_live_lease'],db.execute('SELECT * FROM comparison_live_lease ORDER BY id').fetchall())
            db.execute('DELETE FROM comparison_live_lease WHERE id=%s',(token['lease_id'],))
            self.assertEqual(db.execute('SELECT count(*) n FROM comparison_live_lease').fetchone()['n'],0)
