CREATE OR REPLACE FUNCTION pregame_fee_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    IF TG_OP='UPDATE' AND
        (NEW.state->'last_verified',NEW.state->'review_required',NEW.state->'pricing_rules') IS NOT DISTINCT FROM
        (OLD.state->'last_verified',OLD.state->'review_required',OLD.state->'pricing_rules') THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' THEN v:=split_part(OLD.venue,':',1); ELSE v:=split_part(NEW.venue,':',1); END IF;
    INSERT INTO current_pregame_work(provider,native_event_id)
        SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
        JOIN current_contract c ON c.event_id=e.id WHERE c.venue=v
        ON CONFLICT(provider,native_event_id) DO UPDATE SET revision=current_pregame_work.revision+1,
            admitted_at=clock_timestamp(),error=NULL;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
