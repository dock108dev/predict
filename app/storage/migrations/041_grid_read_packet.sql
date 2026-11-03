-- Cache the exact immutable read row at publication, including captured Originals.
-- Existing projection invalidation/delete/reset triggers own its lifetime.
ALTER TABLE current_grid_projection ADD COLUMN read_packet bytea;
ALTER TABLE current_grid_projection DROP COLUMN retained_bytes;
ALTER TABLE current_grid_projection ADD COLUMN retained_bytes bigint GENERATED ALWAYS AS
    (octet_length(facts::text)+COALESCE(octet_length(read_packet),0)) STORED;
ALTER TABLE latest_board ADD COLUMN read_metadata_bytes bigint GENERATED ALWAYS AS
    (octet_length((facts-'boards')::text)) STORED;
ALTER TABLE current_contract ADD COLUMN facts_bytes bigint GENERATED ALWAYS AS
    (octet_length(facts::text)) STORED;
