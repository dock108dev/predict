CREATE TABLE current_grid_projection (
    game_key text PRIMARY KEY REFERENCES latest_board(game_key) ON DELETE CASCADE,
    facts jsonb NOT NULL,
    retained_bytes bigint GENERATED ALWAYS AS (octet_length(facts::text)) STORED
);
CREATE FUNCTION current_grid_invalidate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM current_grid_projection WHERE game_key=NEW.game_key;
    RETURN NEW;
END;
$$;
CREATE TRIGGER current_grid_invalidate AFTER UPDATE OF facts ON latest_board
    FOR EACH ROW WHEN (OLD.facts IS DISTINCT FROM NEW.facts) EXECUTE FUNCTION current_grid_invalidate();
CREATE FUNCTION current_grid_board(key text, original jsonb) RETURNS jsonb
    LANGUAGE sql STABLE AS $$ SELECT COALESCE((SELECT facts FROM current_grid_projection WHERE game_key=key),original#>'{boards,odds}') $$;
