-- The existing SGO payload table becomes the source of truth for quote bodies.
-- A normalized offer stores its independently accepted receipt, policy fields,
-- and a reference to the exact quote revision. It does not store a second price.
SET LOCAL statement_timeout = '60s';
LOCK TABLE current_offer, current_sgo_reference IN ACCESS EXCLUSIVE MODE;

ALTER TABLE current_sgo_reference RENAME TO sgo_quote_revision;
ALTER TABLE sgo_quote_revision ADD COLUMN is_current boolean NOT NULL DEFAULT true;
ALTER TABLE sgo_quote_revision DROP CONSTRAINT current_sgo_reference_pkey;
ALTER TABLE sgo_quote_revision ADD PRIMARY KEY (id, revision);
CREATE UNIQUE INDEX sgo_quote_current_id ON sgo_quote_revision(id) WHERE is_current;
CREATE VIEW current_sgo_reference AS
    SELECT id, event_id, bookmaker_id, source_order, received_order, expires_at, revision, facts
    FROM sgo_quote_revision WHERE is_current;

ALTER TABLE current_offer RENAME TO current_offer_storage;
ALTER TABLE current_offer_storage ALTER COLUMN price_value DROP NOT NULL;
ALTER TABLE current_offer_storage ADD COLUMN sgo_quote_id text, ADD COLUMN sgo_quote_revision text;
ALTER TABLE current_offer_storage ADD CONSTRAINT current_offer_exact_quote
    FOREIGN KEY (sgo_quote_id, sgo_quote_revision) REFERENCES sgo_quote_revision(id, revision);
ALTER TABLE current_offer_storage ADD CONSTRAINT current_offer_one_price_owner CHECK (
    (price_value IS NOT NULL AND sgo_quote_id IS NULL AND sgo_quote_revision IS NULL)
    OR (price_value IS NULL AND sgo_quote_id IS NOT NULL AND sgo_quote_revision IS NOT NULL
        AND facts#>'{original,value}' IS NULL));
CREATE INDEX current_offer_sgo_quote ON current_offer_storage(sgo_quote_id, sgo_quote_revision)
    WHERE sgo_quote_id IS NOT NULL;

CREATE OR REPLACE FUNCTION current_offer_price_dependency() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE quote_facts jsonb; quote_value text;
BEGIN
    quote_facts := NEW.facts;
    IF NEW.sgo_quote_id IS NOT NULL THEN
        SELECT facts->>'price_american' INTO STRICT quote_value FROM sgo_quote_revision
        WHERE id=NEW.sgo_quote_id AND revision=NEW.sgo_quote_revision;
        IF quote_value IS NULL THEN
            RAISE EXCEPTION 'sgo_offer_source_price_missing';
        END IF;
        quote_facts := jsonb_set(quote_facts, '{original,value}', to_jsonb(quote_value));
    END IF;
    NEW.price_dependency := encode(sha256(convert_to(
        ((quote_facts - ARRAY['times','book_confirmation','provenance']) ||
         jsonb_build_object('provenance',(quote_facts->'provenance')-'sha256'))::text,
        'UTF8')),'hex');
    RETURN NEW;
END;
$$;

-- Backfill only an exact price, original source clock, identity and line.
-- The offer keeps its own literal receipt clock/hash even where the earlier
-- reference reader selected a different receipt of the same source value.
-- A legacy offer without enough matching evidence keeps its self-contained
-- original until replaced by a newly admitted, source-linked page.
CREATE TEMP TABLE sgo_offer_migration ON COMMIT DROP AS
SELECT o.contract_id, o.price_dependency, o.facts, o.price_value,
       r.id AS quote_id, r.revision AS quote_revision
FROM current_offer_storage o
JOIN current_contract_storage c ON c.id=o.contract_id
JOIN current_event e ON e.id=c.event_id
JOIN LATERAL (
    SELECT min(id) AS id,min(revision) AS revision FROM sgo_quote_revision r
    WHERE r.event_id=e.native_event_id AND r.bookmaker_id=c.venue AND r.is_current
      AND r.facts->>'odd_id'=c.native_outcome_id
      AND (r.facts->>'line')::numeric IS NOT DISTINCT FROM (o.facts#>>'{source,native_line}')::numeric
      AND r.facts->>'price_american'=o.price_value
      AND r.facts->>'source_at' IS NOT DISTINCT FROM o.source_at
    HAVING count(*)=1
) r ON true
WHERE e.provider='sportsgameodds' AND o.facts#>>'{original,value}'=o.price_value;

UPDATE current_offer_storage o SET sgo_quote_id=s.quote_id, sgo_quote_revision=s.quote_revision,
    price_value=NULL, facts=o.facts#-'{original,value}'
FROM sgo_offer_migration s WHERE o.contract_id=s.contract_id;

CREATE VIEW current_offer AS
    SELECT o.contract_id, COALESCE(o.price_value, q.facts->>'price_american') AS price_value,
        o.price_units, o.quantity_units, o.source_at, o.source_order, o.received_at, o.received_order,
        CASE WHEN o.sgo_quote_id IS NULL THEN o.facts
             ELSE jsonb_set(o.facts,'{original,value}',q.facts->'price_american') END AS facts,
        o.revision, o.price_dependency
    FROM current_offer_storage o LEFT JOIN sgo_quote_revision q
      ON q.id=o.sgo_quote_id AND q.revision=o.sgo_quote_revision;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM sgo_offer_migration s JOIN current_offer o USING (contract_id)
        WHERE (o.facts,o.price_value,o.price_dependency)
            IS DISTINCT FROM (s.facts,s.price_value,s.price_dependency)
    ) THEN
        RAISE EXCEPTION 'sgo_offer_migration_equivalence';
    END IF;
END;
$$;

-- Preserve ordinary reads and explicit maintenance/fixture DELETEs. The
-- ingestion writer addresses storage directly and owns all source-linked DML.
CREATE FUNCTION write_inline_offer_view() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM current_offer_storage WHERE contract_id=OLD.contract_id;
        RETURN OLD;
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO current_offer_storage
            (contract_id,price_value,price_units,quantity_units,source_at,source_order,received_at,received_order,facts,revision)
        VALUES (NEW.contract_id,NEW.price_value,NEW.price_units,NEW.quantity_units,
                NEW.source_at,NEW.source_order,NEW.received_at,NEW.received_order,NEW.facts,NEW.revision)
        RETURNING price_dependency INTO NEW.price_dependency;
        RETURN NEW;
    END IF;
    UPDATE current_offer_storage SET contract_id=NEW.contract_id,price_value=NEW.price_value,
        price_units=NEW.price_units,quantity_units=NEW.quantity_units,source_at=NEW.source_at,
        source_order=NEW.source_order,received_at=NEW.received_at,received_order=NEW.received_order,
        facts=NEW.facts,revision=NEW.revision
    WHERE contract_id=OLD.contract_id AND sgo_quote_id IS NULL
    RETURNING price_dependency INTO NEW.price_dependency;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source_linked_offer_requires_ingress_owner';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER current_offer_view_write INSTEAD OF INSERT OR UPDATE OR DELETE ON current_offer
    FOR EACH ROW EXECUTE FUNCTION write_inline_offer_view();
