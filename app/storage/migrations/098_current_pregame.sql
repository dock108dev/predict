-- Complete per-offer calculations and durable, coalesced affected-event work.
CREATE TABLE current_pregame_work (
    provider text NOT NULL, native_event_id text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    error text, attempted_at timestamptz,
    PRIMARY KEY(provider,native_event_id)
);
CREATE TABLE current_pregame_calculation (
    contract_id text PRIMARY KEY REFERENCES current_contract_storage(id) ON DELETE CASCADE,
    game_key text NOT NULL, bet_id text, league text NOT NULL, family text NOT NULL,
    venue text NOT NULL, start_at timestamptz NOT NULL, main boolean NOT NULL,
    input_revision text NOT NULL, version text NOT NULL,
    calculated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz NOT NULL,
    net_ev numeric, opportunity_score numeric,
    reason text, payload jsonb,
    CHECK ((reason IS NULL AND payload IS NOT NULL AND net_ev IS NOT NULL AND opportunity_score IS NOT NULL)
        OR (reason IS NOT NULL AND payload IS NULL AND net_ev IS NULL AND opportunity_score IS NULL))
);
CREATE INDEX current_pregame_rank ON current_pregame_calculation
    (opportunity_score DESC,net_ev DESC,bet_id) WHERE reason IS NULL AND main;
CREATE INDEX current_pregame_game ON current_pregame_calculation(game_key,bet_id);
CREATE INDEX current_event_occurrence ON current_event
    (competition,scheduled_start,(facts->>'home'),(facts->>'away'));
CREATE INDEX sgo_event_start ON sgo_event_evidence ((facts->>'starts_at')) WHERE kind='frame';
CREATE TABLE current_pregame_revision (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    revision bigint NOT NULL DEFAULT 0, committed_at timestamptz
);
INSERT INTO current_pregame_revision(singleton) VALUES(true);

CREATE FUNCTION pregame_enqueue(p text,e text) RETURNS void LANGUAGE sql AS $$
    INSERT INTO current_pregame_work(provider,native_event_id) VALUES(p,e)
    ON CONFLICT(provider,native_event_id) DO UPDATE SET revision=current_pregame_work.revision+1,
        admitted_at=clock_timestamp(),error=NULL;
$$;
CREATE FUNCTION pregame_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p text; e text; cid text; eid text;
BEGIN
    IF TG_ARGV[0]='current_event' THEN
        IF TG_OP='UPDATE' AND NEW.revision=OLD.revision THEN RETURN NEW; END IF;
        IF TG_OP='DELETE' THEN p:=OLD.provider; e:=OLD.native_event_id;
        ELSE p:=NEW.provider; e:=NEW.native_event_id; END IF;
    ELSIF TG_ARGV[0]='sgo_quote_revision' THEN
        IF TG_OP='UPDATE' AND NEW.revision=OLD.revision AND NEW.is_current=OLD.is_current AND NEW.facts=OLD.facts THEN RETURN NEW; END IF;
        p:='sportsgameodds';
        IF TG_OP='DELETE' THEN e:=OLD.event_id; ELSE e:=NEW.event_id; END IF;
    ELSIF TG_ARGV[0]='sgo_event_evidence' THEN
        IF TG_OP='UPDATE' AND (NEW.facts-ARRAY['received_at','receipt_sha256','members']) IS NOT DISTINCT FROM
            (OLD.facts-ARRAY['received_at','receipt_sha256','members']) THEN RETURN NEW; END IF;
        p:='sportsgameodds';
        IF TG_OP='DELETE' THEN e:=OLD.event_id; ELSE e:=NEW.event_id; END IF;
    ELSE
        IF TG_ARGV[0]='current_offer_storage' THEN
            IF TG_OP='UPDATE' AND NEW.revision=OLD.revision AND NEW.price_dependency=OLD.price_dependency THEN RETURN NEW; END IF;
        END IF;
        IF TG_ARGV[0]='current_contract_storage' THEN
            IF TG_OP='UPDATE' AND NEW.revision=OLD.revision AND NEW.active=OLD.active THEN RETURN NEW; END IF;
            IF TG_OP='DELETE' THEN eid:=OLD.event_id; ELSE eid:=NEW.event_id; END IF;
        ELSE
            IF TG_OP='DELETE' THEN cid:=OLD.contract_id; ELSE cid:=NEW.contract_id; END IF;
            SELECT event_id INTO eid FROM current_contract_storage WHERE id=cid;
        END IF;
        SELECT provider,native_event_id INTO p,e FROM current_event WHERE id=eid;
    END IF;
    IF p IS NOT NULL AND e IS NOT NULL AND e<>'' THEN PERFORM pregame_enqueue(p,e); END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER pregame_event AFTER INSERT OR UPDATE OR DELETE ON current_event FOR EACH ROW EXECUTE FUNCTION pregame_changed('current_event');
CREATE TRIGGER pregame_contract AFTER INSERT OR UPDATE OR DELETE ON current_contract_storage FOR EACH ROW EXECUTE FUNCTION pregame_changed('current_contract_storage');
CREATE TRIGGER pregame_offer AFTER INSERT OR UPDATE OR DELETE ON current_offer_storage FOR EACH ROW EXECUTE FUNCTION pregame_changed('current_offer_storage');
CREATE TRIGGER pregame_reference AFTER INSERT OR UPDATE OR DELETE ON sgo_quote_revision FOR EACH ROW EXECUTE FUNCTION pregame_changed('sgo_quote_revision');
CREATE TRIGGER pregame_schedule AFTER INSERT OR UPDATE OR DELETE ON sgo_event_evidence FOR EACH ROW EXECUTE FUNCTION pregame_changed('sgo_event_evidence');
INSERT INTO current_pregame_work(provider,native_event_id)
    SELECT provider,native_event_id FROM current_event
    UNION SELECT 'sportsgameodds',event_id FROM current_sgo_event_frame;

CREATE FUNCTION pregame_fee_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    IF TG_OP='UPDATE' AND (NEW.state->'last_verified',NEW.state->'review_required') IS NOT DISTINCT FROM
        (OLD.state->'last_verified',OLD.state->'review_required') THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' THEN v:=split_part(OLD.venue,':',1); ELSE v:=split_part(NEW.venue,':',1); END IF;
    INSERT INTO current_pregame_work(provider,native_event_id)
        SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
        JOIN current_contract c ON c.event_id=e.id WHERE c.venue=v
        ON CONFLICT(provider,native_event_id) DO UPDATE SET revision=current_pregame_work.revision+1,
            admitted_at=clock_timestamp(),error=NULL;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER pregame_fee AFTER INSERT OR UPDATE OR DELETE ON public_fee_schedule
    FOR EACH ROW EXECUTE FUNCTION pregame_fee_changed();
