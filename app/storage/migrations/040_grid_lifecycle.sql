-- Like latest_dashboard, keep source-reset/TRUNCATE chains independent while
-- invalidating every replacement, deletion and reset through owning triggers.
ALTER TABLE current_grid_projection DROP CONSTRAINT current_grid_projection_game_key_fkey;
CREATE FUNCTION current_grid_remove() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='TRUNCATE' THEN
        DELETE FROM current_grid_projection;
        RETURN NULL;
    END IF;
    DELETE FROM current_grid_projection WHERE game_key=CASE WHEN TG_OP='DELETE' THEN OLD.game_key ELSE NEW.game_key END;
    RETURN NULL;
END;
$$;
CREATE TRIGGER current_grid_remove AFTER DELETE OR INSERT ON latest_board
    FOR EACH ROW EXECUTE FUNCTION current_grid_remove();
CREATE TRIGGER current_grid_reset AFTER TRUNCATE ON latest_board
    FOR EACH STATEMENT EXECUTE FUNCTION current_grid_remove();
