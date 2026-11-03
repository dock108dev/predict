-- Independently sealed Originals use the existing immutable packet lease owner.
ALTER TABLE current_result_unit ADD COLUMN original_blob_id text REFERENCES current_grid_blob(id);
INSERT INTO current_grid_blob(id,packet)
 SELECT encode(sha256(convert_to((facts->'selected_frame')::text,'UTF8')),'hex'),
        convert_to((facts->'selected_frame')::text,'UTF8')
 FROM current_result_unit WHERE facts ? 'selected_frame' ON CONFLICT DO NOTHING;
UPDATE current_result_unit SET original_blob_id=encode(sha256(convert_to((facts->'selected_frame')::text,'UTF8')),'hex')
 WHERE facts ? 'selected_frame';
CREATE FUNCTION current_result_original_lifetime() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' AND OLD.original_blob_id IS NOT NULL THEN
  UPDATE current_grid_blob SET unreferenced_at=clock_timestamp() WHERE id=OLD.original_blob_id
   AND NOT EXISTS(SELECT 1 FROM current_result_unit WHERE original_blob_id=OLD.original_blob_id)
   AND NOT EXISTS(SELECT 1 FROM current_grid_projection WHERE blob_id=OLD.original_blob_id);
 END IF;
 IF TG_OP<>'DELETE' AND NEW.original_blob_id IS NOT NULL THEN
  UPDATE current_grid_blob SET unreferenced_at=NULL WHERE id=NEW.original_blob_id;
 END IF;
 RETURN NULL;
END;
$$;
CREATE TRIGGER current_result_original_lifetime AFTER INSERT OR UPDATE OR DELETE ON current_result_unit
 FOR EACH ROW EXECUTE FUNCTION current_result_original_lifetime();
CREATE OR REPLACE FUNCTION current_grid_blob_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE current_grid_blob SET unreferenced_at=clock_timestamp()
 WHERE unreferenced_at IS NULL
  AND NOT EXISTS(SELECT 1 FROM current_grid_projection g WHERE g.blob_id=current_grid_blob.id)
  AND NOT EXISTS(SELECT 1 FROM current_result_unit u WHERE u.original_blob_id=current_grid_blob.id);
 RETURN NULL;
END;
$$;
CREATE TRIGGER current_result_original_truncated AFTER TRUNCATE ON current_result_unit
 FOR EACH STATEMENT EXECUTE FUNCTION current_grid_blob_truncated();
CREATE INDEX current_result_original_blob ON current_result_unit(original_blob_id);
