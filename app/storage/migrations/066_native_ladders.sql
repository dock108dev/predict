-- One exact ordered ladder per outcome/side. Rank insertion no longer rewrites
-- every later level and its indexes. Text values retain decimals and units.
SET LOCAL statement_timeout='60s';
LOCK TABLE current_native_depth IN ACCESS EXCLUSIVE MODE;
CREATE TABLE current_native_ladder (
 venue text NOT NULL, event_id text NOT NULL, native_market_id text NOT NULL,
 native_outcome_id text NOT NULL, side text NOT NULL CHECK(side IN ('asks','bids')),
 levels jsonb NOT NULL CHECK(jsonb_typeof(levels)='array' AND jsonb_array_length(levels) BETWEEN 1 AND 4096),
 PRIMARY KEY(venue,event_id,native_market_id,native_outcome_id,side),
 FOREIGN KEY(venue,event_id,native_market_id) REFERENCES current_native_book(venue,event_id,native_market_id) ON DELETE CASCADE
) PARTITION BY HASH(event_id);
DO $$
DECLARE i integer; child text; differs boolean;
BEGIN
 IF pg_database_size(current_database())+67108864+
    (SELECT COALESCE(sum(pg_total_relation_size(inhrelid)),0) FROM pg_inherits WHERE inhparent='current_native_depth'::regclass)>=2147483648 THEN
   RAISE EXCEPTION 'native_ladder_migration_headroom';
 END IF;
 FOR i IN 0..15 LOOP
  child:='current_native_ladder_p'||lpad(i::text,2,'0');
  EXECUTE format('CREATE TABLE %I PARTITION OF current_native_ladder FOR VALUES WITH (MODULUS 16,REMAINDER %s)',child,i);
  EXECUTE format('ALTER TABLE %I SET (fillfactor=80,autovacuum_vacuum_scale_factor=0.02,toast.autovacuum_vacuum_scale_factor=0.02)',child);
 END LOOP;
END $$;
INSERT INTO current_native_ladder
 SELECT venue,event_id,native_market_id,native_outcome_id,side,
 jsonb_agg(jsonb_build_array(price_value,price_units,quantity_value,quantity_units) ORDER BY level)
 FROM current_native_depth GROUP BY venue,event_id,native_market_id,native_outcome_id,side;
ALTER TABLE current_native_depth RENAME TO current_native_depth_ranked;
CREATE VIEW current_native_depth AS
 SELECT venue,event_id,native_market_id,native_outcome_id,side,(position-1)::integer level,
 value->>0 price_value,value->>1 price_units,value->>2 quantity_value,value->>3 quantity_units
 FROM current_native_ladder CROSS JOIN LATERAL jsonb_array_elements(levels) WITH ORDINALITY AS l(value,position);
DO $$
BEGIN
 IF EXISTS((SELECT * FROM current_native_depth_ranked EXCEPT ALL SELECT * FROM current_native_depth)
   UNION ALL (SELECT * FROM current_native_depth EXCEPT ALL SELECT * FROM current_native_depth_ranked)) THEN
  RAISE EXCEPTION 'native_ladder_migration_equivalence';
 END IF;
END $$;
DROP TABLE current_native_depth_ranked;
