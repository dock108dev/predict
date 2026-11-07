-- Bound physical replacement units across the remaining large working owners.
-- This is one exact, locked cutover; no data or lease expiration is changed.
SET LOCAL statement_timeout='60s';
DO $$
DECLARE targets text[]:=ARRAY['current_contract','current_offer'];
 allowed text[]:=ARRAY['current_contract','current_offer','current_depth','current_native_depth',
 'comparison_snapshot','comparison_snapshot_result','comparison_live_read_fragment',
 'comparison_snapshot_head','comparison_snapshot_review','comparison_live_head',
 'comparison_live_component','comparison_live_member','comparison_live_lease'];
 owner text; staged text; child text; columns text; key_columns text; item record;
 i integer; copy_bytes bigint; differs boolean;
BEGIN
 -- Lock dependencies as well as replaced owners before inspecting constraints.
 FOR owner IN SELECT unnest(allowed||ARRAY['current_event','current_native_book']) ORDER BY 1 LOOP
  EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE',owner);
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_constraint WHERE contype='f' AND conparentid=0
   AND confrelid IN(SELECT unnest(targets)::regclass)
   AND conrelid::regclass::text<>ALL(allowed)) THEN
  RAISE EXCEPTION 'working_partition_unknown_foreign_dependency';
 END IF;
 SELECT sum(pg_total_relation_size(x::regclass)) INTO copy_bytes FROM unnest(targets)x;
 IF pg_database_size(current_database())+copy_bytes+67108864>=2147483648 THEN
  RAISE EXCEPTION 'working_partition_headroom';
 END IF;
 CREATE TEMP TABLE working_partition_foreign_keys ON COMMIT DROP AS
  SELECT conrelid::regclass::text owner,conname,pg_get_constraintdef(oid) definition
  FROM pg_constraint WHERE contype='f' AND conparentid=0 AND
   (conrelid IN(SELECT unnest(targets)::regclass) OR confrelid IN(SELECT unnest(targets)::regclass));
 CREATE TEMP TABLE working_partition_triggers ON COMMIT DROP AS
  SELECT tgrelid::regclass::text owner,tgname,tgenabled,pg_get_triggerdef(oid) definition FROM pg_trigger
  WHERE tgrelid IN(SELECT unnest(targets)::regclass) AND NOT tgisinternal;
 FOREACH owner IN ARRAY targets LOOP
  staged:=owner||'_partitioned';
  key_columns:=CASE owner WHEN 'current_offer' THEN 'contract_id'
    WHEN 'current_native_depth' THEN 'event_id'
    WHEN 'comparison_live_read_fragment' THEN 'member_id' ELSE 'id' END;
  EXECUTE format('CREATE TABLE %I (LIKE %I INCLUDING ALL) PARTITION BY HASH(%s)',staged,owner,key_columns);
  FOR i IN 0..15 LOOP
   child:=owner||'_p'||lpad(i::text,2,'0');
   EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES WITH (MODULUS 16,REMAINDER %s)',child,staged,i);
   EXECUTE format('ALTER TABLE %I SET (autovacuum_vacuum_scale_factor=0.02,toast.autovacuum_vacuum_scale_factor=0.02)',child);
  END LOOP;
  SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) INTO columns
    FROM pg_attribute WHERE attrelid=owner::regclass AND attnum>0 AND NOT attisdropped AND attgenerated='';
  EXECUTE format('INSERT INTO %I(%s) SELECT %s FROM %I',staged,columns,columns,owner);
  -- EXCEPT ALL covers every exact column, including bytea originals and leases.
  EXECUTE format('SELECT EXISTS((SELECT * FROM %I EXCEPT ALL SELECT * FROM %I)
    UNION ALL (SELECT * FROM %I EXCEPT ALL SELECT * FROM %I))',owner,staged,staged,owner) INTO differs;
  IF differs THEN RAISE EXCEPTION 'working_partition_equivalence: %',owner; END IF;
 END LOOP;
 FOR item IN SELECT * FROM working_partition_foreign_keys LOOP
  EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',item.owner,item.conname);
 END LOOP;
 FOREACH owner IN ARRAY targets LOOP
  EXECUTE format('ALTER TABLE %I RENAME TO %I',owner,owner||'_unpartitioned');
  EXECUTE format('ALTER TABLE %I RENAME TO %I',owner||'_partitioned',owner);
 END LOOP;
 FOR item IN SELECT * FROM working_partition_foreign_keys LOOP
  EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',item.owner,item.conname,item.definition);
 END LOOP;
 -- Dependency hashing triggers are installed after exact copying, not used to
 -- manufacture new revisions during upgrade. Their original definitions remain.
 FOR item IN SELECT * FROM working_partition_triggers LOOP
  EXECUTE item.definition;
  IF item.tgenabled<>'O' THEN
   EXECUTE format('ALTER TABLE %s %s TRIGGER %I',item.owner,
     CASE item.tgenabled WHEN 'D' THEN 'DISABLE' WHEN 'R' THEN 'ENABLE REPLICA' ELSE 'ENABLE ALWAYS' END,item.tgname);
  END IF;
 END LOOP;
 FOREACH owner IN ARRAY targets LOOP
  -- A view or other unrecognized dependent refuses this drop atomically.
  EXECUTE format('DROP TABLE %I',owner||'_unpartitioned');
 END LOOP;
 DROP TABLE pg_temp.working_partition_foreign_keys,pg_temp.working_partition_triggers;
END $$;
