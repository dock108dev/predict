-- Keep complete current raw evidence while bounding each reclamation copy.
SET LOCAL statement_timeout='60s';
LOCK TABLE current_acquisition_image,current_acquisition_market IN ACCESS EXCLUSIVE MODE;
DO $$
DECLARE owner text; staged text; old_table text; child text; columns text; i integer; differs boolean;
BEGIN
 IF pg_database_size(current_database())+pg_total_relation_size('current_acquisition_image')
    +pg_total_relation_size('current_acquisition_market')+67108864>=2147483648 THEN
  RAISE EXCEPTION 'acquisition_partition_headroom';
 END IF;
 FOREACH owner IN ARRAY ARRAY['current_acquisition_image','current_acquisition_market'] LOOP
  staged:=owner||'_partitioned'; old_table:=owner||'_unpartitioned';
  EXECUTE format('CREATE TABLE %I (LIKE %I INCLUDING ALL) PARTITION BY HASH(source,event_id,market_id)',staged,owner);
  FOR i IN 0..15 LOOP
   child:=owner||'_p'||lpad(i::text,2,'0');
   EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES WITH (MODULUS 16,REMAINDER %s)',child,staged,i);
   EXECUTE format('ALTER TABLE %I SET (autovacuum_vacuum_scale_factor=0.02,toast.autovacuum_vacuum_scale_factor=0.02)',child);
  END LOOP;
  SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) INTO columns
    FROM pg_attribute WHERE attrelid=owner::regclass AND attnum>0 AND NOT attisdropped AND attgenerated='';
  EXECUTE format('INSERT INTO %I(%s) SELECT %s FROM %I',staged,columns,columns,owner);
  EXECUTE format('SELECT (SELECT count(*) FROM %I)<>(SELECT count(*) FROM %I)
    OR EXISTS(SELECT 1 FROM %I old LEFT JOIN %I new USING(source,event_id,market_id)
      WHERE new.source IS NULL OR ROW(old.*) IS DISTINCT FROM ROW(new.*))',owner,staged,owner,staged) INTO differs;
  IF differs THEN RAISE EXCEPTION 'acquisition_partition_equivalence: %',owner; END IF;
  -- Install after copying: an upgrade must not mint new persistence timestamps.
  IF owner='current_acquisition_image' THEN
   EXECUTE format('CREATE TRIGGER raw_persistence BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION raw_persistence_clock()',staged);
  END IF;
  EXECUTE format('ALTER TABLE %I RENAME TO %I',owner,old_table);
  EXECUTE format('ALTER TABLE %I RENAME TO %I',staged,owner);
  -- Unexpected dependencies fail and roll back; never cascade into evidence.
  EXECUTE format('DROP TABLE %I',old_table);
 END LOOP;
END $$;
