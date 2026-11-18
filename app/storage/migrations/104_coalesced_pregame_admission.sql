-- One serialized source transaction needs one durable job per affected game.
ALTER TABLE current_pregame_work ADD COLUMN admission_xid xid8;

CREATE OR REPLACE FUNCTION pregame_enqueue(p text,e text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(901095);
    INSERT INTO current_pregame_work(provider,native_event_id,admission_xid)
        VALUES(p,e,pg_current_xact_id())
    ON CONFLICT(provider,native_event_id) DO UPDATE
        SET revision=current_pregame_work.revision+1,admitted_at=clock_timestamp(),
            error=NULL,admission_xid=excluded.admission_xid
        WHERE current_pregame_work.admission_xid IS DISTINCT FROM excluded.admission_xid
            OR current_pregame_work.error IS NOT NULL;
END $$;

-- INSERT ... ON CONFLICT fires both statement triggers even when its guarded
-- update changes nothing. A row trigger publishes only actual queued changes.
DROP TRIGGER pregame_work_revision ON current_pregame_work;
CREATE TRIGGER pregame_work_revision AFTER INSERT OR UPDATE ON current_pregame_work
    FOR EACH ROW EXECUTE FUNCTION pregame_work_changed();
