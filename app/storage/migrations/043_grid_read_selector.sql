-- Avoid decompressing the full selected-evidence row to get a tiny selector.
ALTER TABLE current_grid_projection ADD COLUMN read_selector jsonb;
UPDATE current_grid_projection g SET read_selector=b.facts#>'{publication_dependencies,selector}' FROM latest_board b WHERE b.game_key=g.game_key;
ALTER TABLE current_grid_projection DROP COLUMN retained_bytes;
ALTER TABLE current_grid_projection ADD COLUMN retained_bytes bigint GENERATED ALWAYS AS
 (octet_length(facts::text)+COALESCE(octet_length(read_packet),0)+COALESCE(octet_length(read_selector::text),0)) STORED;
