-- Keep at most one catalog turn of revoked native contract bodies for exact
-- readmission. All existing readers continue to use the active relation.
SET LOCAL lock_timeout='5s';
LOCK TABLE current_contract IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
 IF EXISTS (SELECT FROM pg_depend d JOIN pg_rewrite r ON r.oid=d.objid
            WHERE d.classid='pg_rewrite'::regclass AND d.refobjid='current_contract'::regclass) THEN
   RAISE EXCEPTION 'contract_membership_unknown_dependent_view';
 END IF;
END $$;
ALTER TABLE current_contract RENAME TO current_contract_storage;
ALTER TABLE current_contract_storage ADD COLUMN active boolean NOT NULL DEFAULT true;
CREATE INDEX current_contract_inactive ON current_contract_storage(id) WHERE NOT active;
CREATE VIEW current_contract AS
 SELECT id,event_id,venue,native_market_id,native_outcome_id,native_side,facts,revision,
        contract_dependency,metric_dependency,facts_bytes,candidate_projection
 FROM current_contract_storage WHERE active;

-- A normal insert revalidates the complete normalized body and every key.
-- A changed member takes the ordinary insertion and dependency-trigger path.
CREATE FUNCTION readmit_current_contract() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT FROM current_contract_storage WHERE id=NEW.id AND NOT active) THEN
   UPDATE current_contract_storage SET active=true WHERE id=NEW.id AND NOT active
     AND (revision,event_id,venue,native_market_id,native_outcome_id,native_side,facts)
       = (NEW.revision,NEW.event_id,NEW.venue,NEW.native_market_id,NEW.native_outcome_id,NEW.native_side,NEW.facts);
   IF FOUND THEN RETURN NULL; END IF;
   DELETE FROM current_contract_storage WHERE id=NEW.id AND NOT active;
 END IF;
 RETURN NEW;
END $$;
-- Run ahead of the expensive derived-body triggers on exact reactivation.
CREATE TRIGGER aa_readmit_current_contract BEFORE INSERT ON current_contract_storage
 FOR EACH ROW EXECUTE FUNCTION readmit_current_contract();
