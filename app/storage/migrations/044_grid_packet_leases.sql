-- Move immutable published evidence behind references, rather than transfer
-- every game's Originals before returning the first page. No price history.
CREATE TABLE current_grid_blob (
 id text PRIMARY KEY CHECK(length(id)=64), packet bytea NOT NULL,
 retained_bytes bigint GENERATED ALWAYS AS (octet_length(packet)) STORED,
 unreferenced_at timestamptz
);
CREATE TABLE current_grid_read_lease (
 token text PRIMARY KEY,expires_at timestamptz NOT NULL,packet_ids text[] NOT NULL
);
ALTER TABLE current_grid_projection ADD COLUMN blob_id text REFERENCES current_grid_blob(id);
ALTER TABLE current_grid_projection ADD COLUMN blob_bytes bigint NOT NULL DEFAULT 0;
INSERT INTO current_grid_blob(id,packet)
 SELECT encode(sha256(read_packet),'hex'),read_packet FROM current_grid_projection WHERE read_packet IS NOT NULL ON CONFLICT DO NOTHING;
UPDATE current_grid_projection SET blob_id=encode(sha256(read_packet),'hex'),blob_bytes=octet_length(read_packet),read_packet=NULL WHERE read_packet IS NOT NULL;
ALTER TABLE current_grid_projection DROP COLUMN retained_bytes;
ALTER TABLE current_grid_projection ADD COLUMN retained_bytes bigint GENERATED ALWAYS AS
 (octet_length(facts::text)+COALESCE(octet_length(read_packet),0)+COALESCE(octet_length(read_selector::text),0)+blob_bytes) STORED;
CREATE FUNCTION current_grid_blob_lifetime() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' AND OLD.blob_id IS NOT NULL THEN
  UPDATE current_grid_blob SET unreferenced_at=clock_timestamp() WHERE id=OLD.blob_id
    AND NOT EXISTS(SELECT 1 FROM current_grid_projection WHERE blob_id=OLD.blob_id);
 END IF;
 IF TG_OP<>'DELETE' AND NEW.blob_id IS NOT NULL THEN
  UPDATE current_grid_blob SET unreferenced_at=NULL WHERE id=NEW.blob_id AND unreferenced_at IS NOT NULL;
 END IF;
 RETURN NULL;
END;
$$;
CREATE TRIGGER current_grid_blob_lifetime AFTER INSERT OR UPDATE OR DELETE ON current_grid_projection
 FOR EACH ROW EXECUTE FUNCTION current_grid_blob_lifetime();
CREATE FUNCTION current_grid_blob_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE current_grid_blob SET unreferenced_at=clock_timestamp()
 WHERE unreferenced_at IS NULL AND NOT EXISTS(SELECT 1 FROM current_grid_projection g WHERE g.blob_id=current_grid_blob.id);
 RETURN NULL;
END;
$$;
CREATE TRIGGER current_grid_blob_truncated AFTER TRUNCATE ON current_grid_projection
 FOR EACH STATEMENT EXECUTE FUNCTION current_grid_blob_truncated();
