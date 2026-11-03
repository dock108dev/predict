-- Parent fallback evidence remains inspectable after working result reclamation.
-- Store references, not another encoded Original in every parent publication.
CREATE TABLE current_result_parent_original (
    game_key text NOT NULL REFERENCES latest_board(game_key) ON DELETE CASCADE,
    unit_id text NOT NULL,
    blob_id text NOT NULL REFERENCES current_grid_blob(id),
    PRIMARY KEY(game_key,unit_id)
);
CREATE INDEX current_result_parent_original_blob ON current_result_parent_original(blob_id);
CREATE FUNCTION current_parent_original_released() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE current_grid_blob SET unreferenced_at=clock_timestamp() WHERE id=OLD.blob_id;
    RETURN OLD;
END;
$$;
CREATE TRIGGER current_parent_original_release AFTER DELETE ON current_result_parent_original
    FOR EACH ROW EXECUTE FUNCTION current_parent_original_released();
