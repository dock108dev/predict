-- Every queue producer uses the current-writer lock before the coalesced row.
CREATE OR REPLACE FUNCTION pregame_enqueue(p text,e text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(901095);
    INSERT INTO current_pregame_work(provider,native_event_id) VALUES(p,e)
    ON CONFLICT(provider,native_event_id) DO UPDATE SET revision=current_pregame_work.revision+1,
        admitted_at=clock_timestamp(),error=NULL;
END $$;
CREATE FUNCTION pregame_fee_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(901095);
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER pregame_fee_writer BEFORE INSERT OR UPDATE OR DELETE ON public_fee_schedule
    FOR EACH ROW EXECUTE FUNCTION pregame_fee_lock();
