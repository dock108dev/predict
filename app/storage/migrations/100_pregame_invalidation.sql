-- Eligibility changes are visible to the cheap browser cursor before recovery.
CREATE FUNCTION pregame_work_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE current_pregame_revision SET revision=revision+1 WHERE singleton;
    RETURN NEW;
END $$;
CREATE TRIGGER pregame_work_revision AFTER INSERT OR UPDATE ON current_pregame_work
    FOR EACH STATEMENT EXECUTE FUNCTION pregame_work_changed();
