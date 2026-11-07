-- Bound the temporary copy needed to reclaim replaceable recovery evidence.
-- Logical identity and complete catalog transactions are unchanged.
SET LOCAL statement_timeout='60s';
LOCK TABLE current_native_catalog_recovery,current_native_market_recovery IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF pg_database_size(current_database())+pg_total_relation_size('current_native_market_recovery')+67108864>=2147483648 THEN
  RAISE EXCEPTION 'recovery_partition_headroom';
 END IF;
END $$;
ALTER TABLE current_native_market_recovery RENAME TO current_native_market_recovery_unpartitioned;
CREATE TABLE current_native_market_recovery (
 source text NOT NULL REFERENCES current_native_catalog_recovery(source) ON DELETE CASCADE,
 market_id text NOT NULL, metadata jsonb NOT NULL, parsed jsonb,
 display_metadata jsonb GENERATED ALWAYS AS
 (jsonb_set(jsonb_set(jsonb_set('{}'::jsonb,'{title}',COALESCE(metadata->'title','null'::jsonb)),
 '{period}',COALESCE(metadata->'period','null'::jsonb)),'{sides}',COALESCE(metadata->'sides','null'::jsonb))) STORED,
 CONSTRAINT native_recovery_partition_identity PRIMARY KEY(source,market_id)
) PARTITION BY HASH(source,market_id);
DO $$ DECLARE i integer; child text; BEGIN
 FOR i IN 0..15 LOOP
  child:='current_native_market_recovery_p'||lpad(i::text,2,'0');
  EXECUTE format('CREATE TABLE %I PARTITION OF current_native_market_recovery FOR VALUES WITH (MODULUS 16,REMAINDER %s)',child,i);
  EXECUTE format('ALTER TABLE %I SET (autovacuum_vacuum_scale_factor=0.02,toast.autovacuum_vacuum_scale_factor=0.02)',child);
 END LOOP;
END $$;
INSERT INTO current_native_market_recovery(source,market_id,metadata,parsed)
 SELECT source,market_id,metadata,parsed FROM current_native_market_recovery_unpartitioned;
DO $$ BEGIN
 IF (SELECT count(*) FROM current_native_market_recovery)<>(SELECT count(*) FROM current_native_market_recovery_unpartitioned)
 OR EXISTS (SELECT 1 FROM current_native_market_recovery_unpartitioned old
   LEFT JOIN current_native_market_recovery new USING(source,market_id)
   WHERE new.source IS NULL OR (old.metadata,old.parsed,old.display_metadata)
      IS DISTINCT FROM (new.metadata,new.parsed,new.display_metadata)) THEN
  RAISE EXCEPTION 'recovery_partition_equivalence';
 END IF;
END $$;
-- No CASCADE: an unexpected dependent object must roll back the migration.
DROP TABLE current_native_market_recovery_unpartitioned;
