-- Exact logical accounting and retirement metadata, computed once per write.
-- The publication lock must not repeatedly detoast every unrelated board.
ALTER TABLE latest_board
 ADD COLUMN retained_bytes bigint GENERATED ALWAYS AS (octet_length(facts::text)) STORED,
 ADD COLUMN publication_events jsonb GENERATED ALWAYS AS (facts#>'{publication_dependencies,selector,events}') STORED,
 ADD COLUMN observation_as_of text GENERATED ALWAYS AS (facts#>>'{boards,odds,as_of}') STORED;
