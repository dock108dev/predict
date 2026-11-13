-- Exact native offers name an immutable book. The same book and every reusable
-- ladder body serve both the current market and an older still-retained offer.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(901095);
LOCK TABLE current_native_book,current_native_ladder,current_offer_storage,current_contract_storage,current_depth
    IN ACCESS EXCLUSIVE MODE;

CREATE FUNCTION native_ladder_id(body jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT encode(sha256(convert_to(body::text,'UTF8')),'hex')
$$;
CREATE FUNCTION native_ladder_ids(refs jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT COALESCE(array_agg(DISTINCT id ORDER BY id),'{}')
    FROM jsonb_each(refs) AS outcome(outcome_id,sides)
    CROSS JOIN LATERAL jsonb_each_text(outcome.sides) AS side(side,id)
$$;

CREATE TABLE native_ladder_revision (
    id text PRIMARY KEY CHECK(id=native_ladder_id(levels)),
    levels jsonb NOT NULL CHECK(jsonb_typeof(levels)='array' AND jsonb_array_length(levels) BETWEEN 1 AND 4096)
);

CREATE TABLE native_book_revision (
    id text PRIMARY KEY,
    venue text NOT NULL,
    event_id text NOT NULL REFERENCES current_event(id) ON DELETE CASCADE,
    native_market_id text NOT NULL,
    source_at text,
    source_order numeric,
    received_at text NOT NULL,
    received_order numeric NOT NULL,
    revision text NOT NULL,
    quantity_units text NOT NULL,
    state text NOT NULL,
    sync text NOT NULL,
    sequence text,
    outcomes jsonb NOT NULL,
    confirmation jsonb,
    depth_revision text,
    ladder_refs jsonb NOT NULL CHECK(jsonb_typeof(ladder_refs)='object'),
    ladder_ids text[] GENERATED ALWAYS AS (native_ladder_ids(ladder_refs)) STORED,
    is_current boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX native_book_head ON native_book_revision(venue,event_id,native_market_id) WHERE is_current;
CREATE INDEX native_book_event ON native_book_revision(event_id);
CREATE INDEX native_book_ladder_refs ON native_book_revision USING gin(ladder_ids);
CREATE INDEX native_book_retention ON native_book_revision(id) WHERE NOT is_current;

CREATE FUNCTION native_ladder_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'native_ladder_revision_immutable'; END IF;
    RETURN OLD;
END
$$;
CREATE TRIGGER native_ladder_immutable BEFORE UPDATE ON native_ladder_revision
    FOR EACH ROW EXECUTE FUNCTION native_ladder_immutable();

CREATE FUNCTION native_book_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF EXISTS (SELECT 1 FROM unnest(native_ladder_ids(NEW.ladder_refs)) AS used(id)
                   WHERE NOT EXISTS(SELECT 1 FROM native_ladder_revision d WHERE d.id=used.id)) THEN
            RAISE EXCEPTION 'native_book_ladder_missing';
        END IF;
    ELSIF (to_jsonb(NEW)-'is_current'-'ladder_ids') IS DISTINCT FROM (to_jsonb(OLD)-'is_current'-'ladder_ids') THEN
        RAISE EXCEPTION 'native_book_revision_immutable';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER native_book_immutable BEFORE INSERT OR UPDATE ON native_book_revision
    FOR EACH ROW EXECUTE FUNCTION native_book_immutable();

INSERT INTO native_ladder_revision(id,levels)
    SELECT DISTINCT native_ladder_id(levels),levels FROM current_native_ladder;
INSERT INTO native_book_revision(id,venue,event_id,native_market_id,source_at,source_order,received_at,
    received_order,revision,quantity_units,state,sync,sequence,outcomes,confirmation,depth_revision,ladder_refs)
SELECT 'imported:'||encode(sha256(convert_to(to_jsonb(b)::text,'UTF8')),'hex'),
    b.*,COALESCE(l.refs,'{}')
FROM current_native_book b
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(native_outcome_id,sides) AS refs FROM (
        SELECT native_outcome_id,jsonb_object_agg(side,native_ladder_id(levels)) AS sides
        FROM current_native_ladder d WHERE (d.venue,d.event_id,d.native_market_id)=(b.venue,b.event_id,b.native_market_id)
        GROUP BY native_outcome_id) x) l ON true;

ALTER TABLE current_native_book RENAME TO native_book_before_086;
ALTER TABLE current_native_ladder RENAME TO native_ladder_before_086;
CREATE VIEW current_native_book AS
    SELECT venue,event_id,native_market_id,source_at,source_order,received_at,received_order,revision,
           quantity_units,state,sync,sequence,outcomes,confirmation,depth_revision
    FROM native_book_revision WHERE is_current;
CREATE VIEW current_native_ladder AS
    SELECT b.venue,b.event_id,b.native_market_id,o.native_outcome_id,s.side,d.levels
    FROM native_book_revision b CROSS JOIN LATERAL jsonb_each(b.ladder_refs) AS o(native_outcome_id,sides)
    CROSS JOIN LATERAL jsonb_each_text(o.sides) AS s(side,id)
    JOIN native_ladder_revision d ON d.id=s.id WHERE b.is_current;
CREATE OR REPLACE VIEW current_native_depth AS
    SELECT venue,event_id,native_market_id,native_outcome_id,side,(position-1)::integer level,
           value->>0 price_value,value->>1 price_units,value->>2 quantity_value,value->>3 quantity_units
    FROM current_native_ladder CROSS JOIN LATERAL jsonb_array_elements(levels) WITH ORDINALITY AS l(value,position);
DO $$
BEGIN
    IF EXISTS ((SELECT * FROM native_book_before_086 EXCEPT ALL SELECT * FROM current_native_book)
        UNION ALL (SELECT * FROM current_native_book EXCEPT ALL SELECT * FROM native_book_before_086)) OR
        EXISTS ((SELECT * FROM native_ladder_before_086 EXCEPT ALL SELECT * FROM current_native_ladder)
        UNION ALL (SELECT * FROM current_native_ladder EXCEPT ALL SELECT * FROM native_ladder_before_086)) THEN
        RAISE EXCEPTION 'native_book_migration_equivalence';
    END IF;
END
$$;
DROP TABLE native_ladder_before_086,native_book_before_086;

ALTER TABLE current_offer_storage ADD COLUMN native_book_id text,
    ADD COLUMN native_bid_outcome_id text;
ALTER TABLE current_offer_storage ADD CONSTRAINT current_offer_exact_native_book
    FOREIGN KEY(native_book_id) REFERENCES native_book_revision(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE current_offer_storage DROP CONSTRAINT current_offer_one_price_owner;
ALTER TABLE current_offer_storage ADD CONSTRAINT current_offer_one_price_owner CHECK (
    (price_value IS NOT NULL AND sgo_quote_id IS NULL AND sgo_quote_revision IS NULL
      AND native_book_id IS NULL AND native_bid_outcome_id IS NULL)
    OR (price_value IS NULL AND sgo_quote_id IS NOT NULL AND sgo_quote_revision IS NOT NULL
      AND native_book_id IS NULL AND native_bid_outcome_id IS NULL AND facts#>'{original,value}' IS NULL)
    OR (price_value IS NULL AND sgo_quote_id IS NULL AND sgo_quote_revision IS NULL
      AND native_book_id IS NOT NULL AND facts#>'{original,value}' IS NULL AND facts#>'{original,native_value}' IS NULL
      AND (native_bid_outcome_id IS NOT NULL)=(facts#>>'{original,transformation}' IS NOT DISTINCT FROM 'one_minus_native_bid'))
);
CREATE INDEX current_offer_native_book ON current_offer_storage(native_book_id) WHERE native_book_id IS NOT NULL;

CREATE OR REPLACE FUNCTION current_offer_price_dependency() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE quote_facts jsonb; quote_value text; native_bid text;
BEGIN
    quote_facts := NEW.facts;
    IF NEW.sgo_quote_id IS NOT NULL THEN
        SELECT facts->>'price_american' INTO STRICT quote_value FROM sgo_quote_revision
        WHERE id=NEW.sgo_quote_id AND revision=NEW.sgo_quote_revision;
        IF quote_value IS NULL THEN RAISE EXCEPTION 'sgo_offer_source_price_missing'; END IF;
        quote_facts := jsonb_set(quote_facts,'{original,value}',to_jsonb(quote_value));
    ELSIF NEW.native_book_id IS NOT NULL THEN
        SELECT a.levels->0->>0, p.levels->0->>0 INTO STRICT quote_value,native_bid
        FROM native_book_revision b JOIN current_contract_storage c ON c.id=NEW.contract_id
        JOIN current_event e ON e.id=c.event_id
        JOIN native_ladder_revision a ON a.id=b.ladder_refs#>>ARRAY[c.native_outcome_id,'asks']
        LEFT JOIN native_ladder_revision p ON p.id=b.ladder_refs#>>ARRAY[NEW.native_bid_outcome_id,'bids']
        WHERE b.id=NEW.native_book_id AND e.provider=c.venue
            AND (b.venue,b.event_id,b.native_market_id)=(c.venue,c.event_id,c.native_market_id)
            AND (b.received_at,b.source_at,b.confirmation) IS NOT DISTINCT FROM
                (NEW.received_at,NEW.source_at,NEW.facts->'book_confirmation')
            AND a.levels->0->>1=NEW.price_units AND a.levels->0->>3=NEW.quantity_units
            AND (NEW.native_bid_outcome_id IS NULL OR (c.native_outcome_id<>NEW.native_bid_outcome_id
                AND NEW.facts#>>'{original,native_units}'=p.levels->0->>1
                AND (a.levels->0->>0)::numeric+(p.levels->0->>0)::numeric=1));
        quote_facts := jsonb_set(quote_facts,'{original,value}',to_jsonb(quote_value));
        IF native_bid IS NOT NULL THEN
            quote_facts := jsonb_set(quote_facts,'{original,native_value}',to_jsonb(native_bid));
        END IF;
    END IF;
    NEW.price_dependency := encode(sha256(convert_to(
        ((quote_facts - ARRAY['times','book_confirmation','provenance']) ||
         jsonb_build_object('provenance',(quote_facts->'provenance')-'sha256'))::text,
        'UTF8')),'hex');
    RETURN NEW;
END
$$;

CREATE OR REPLACE VIEW current_offer AS
    SELECT o.contract_id,COALESCE(o.price_value,q.facts->>'price_american',a.levels->0->>0) AS price_value,
        o.price_units,o.quantity_units,o.source_at,o.source_order,o.received_at,o.received_order,
        CASE WHEN o.sgo_quote_id IS NOT NULL THEN jsonb_set(o.facts,'{original,value}',q.facts->'price_american')
             WHEN o.native_bid_outcome_id IS NOT NULL THEN
               jsonb_set(jsonb_set(o.facts,'{original,value}',a.levels->0->0),'{original,native_value}',p.levels->0->0)
             WHEN o.native_book_id IS NOT NULL THEN jsonb_set(o.facts,'{original,value}',a.levels->0->0)
             ELSE o.facts END AS facts,
        o.revision,o.price_dependency,o.native_book_id,b.revision AS native_book_revision
    FROM current_offer_storage o
    LEFT JOIN sgo_quote_revision q ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision)
    LEFT JOIN native_book_revision b ON b.id=o.native_book_id
    LEFT JOIN native_ladder_revision a ON a.id=b.ladder_refs#>>ARRAY[o.facts#>>'{source,native_outcome_id}','asks']
    LEFT JOIN native_ladder_revision p ON p.id=b.ladder_refs#>>ARRAY[o.native_bid_outcome_id,'bids'];

CREATE OR REPLACE FUNCTION write_inline_offer_view() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        DELETE FROM current_offer_storage WHERE contract_id=OLD.contract_id;
        RETURN OLD;
    ELSIF TG_OP='INSERT' THEN
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
    WHERE contract_id=OLD.contract_id AND sgo_quote_id IS NULL AND native_book_id IS NULL
    RETURNING price_dependency INTO NEW.price_dependency;
    IF NOT FOUND THEN RAISE EXCEPTION 'source_linked_offer_requires_ingress_owner'; END IF;
    RETURN NEW;
END
$$;

-- Link only text-exact values and clocks. A formerly standalone observation
-- stays readable when no matching book has ever been retained.
CREATE FUNCTION link_native_offers(offer_ids text[], book_ids text[]) RETURNS integer LANGUAGE sql AS $$
    WITH exact AS (
        SELECT o.contract_id,b.id AS book_id,p.native_outcome_id AS bid_outcome_id
        FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id AND e.provider=c.venue
        JOIN native_book_revision b ON (b.venue,b.event_id,b.native_market_id)=(c.venue,c.event_id,c.native_market_id)
            AND b.is_current
        JOIN native_ladder_revision a ON a.id=b.ladder_refs#>>ARRAY[c.native_outcome_id,'asks']
        LEFT JOIN LATERAL (
            SELECT side.key AS native_outcome_id
            FROM jsonb_each(b.ladder_refs) side
            JOIN native_ladder_revision bid ON bid.id=side.value->>'bids'
            WHERE o.facts#>>'{original,transformation}'='one_minus_native_bid'
              AND side.key<>c.native_outcome_id
              AND (o.facts#>>'{original,native_value}',o.facts#>>'{original,native_units}')=
                  (bid.levels->0->>0,bid.levels->0->>1)
              AND (a.levels->0->>0)::numeric+(bid.levels->0->>0)::numeric=1
        ) p ON true
        WHERE o.price_value IS NOT NULL AND o.sgo_quote_id IS NULL AND c.active
            AND (offer_ids IS NULL OR o.contract_id=ANY(offer_ids)) AND (book_ids IS NULL OR b.id=ANY(book_ids))
            AND o.facts#>>'{source,native_outcome_id}'=c.native_outcome_id
            AND o.facts#>>'{source,provider}'=e.provider
            AND o.facts#>>'{source,native_event_id}'=e.native_event_id
            AND o.facts#>>'{source,native_market_id}'=c.native_market_id
            AND (o.price_value,o.price_units,o.quantity_units)=(a.levels->0->>0,a.levels->0->>1,a.levels->0->>3)
            AND o.facts#>>'{original,value}'=o.price_value
            AND (b.received_at,b.source_at,b.confirmation) IS NOT DISTINCT FROM
                (o.received_at,o.source_at,o.facts->'book_confirmation')
            AND ((p.native_outcome_id IS NULL AND o.facts#>'{original,native_value}' IS NULL
                AND o.facts#>>'{original,transformation}' IS DISTINCT FROM 'one_minus_native_bid')
                OR (p.native_outcome_id IS NOT NULL AND jsonb_array_length(b.outcomes)=2))
    ), linked AS (
        UPDATE current_offer_storage o SET native_book_id=x.book_id,native_bid_outcome_id=x.bid_outcome_id,
            price_value=NULL,facts=o.facts#-'{original,value}'#-'{original,native_value}'
        FROM exact x WHERE x.contract_id=o.contract_id RETURNING 1
    ) SELECT count(*)::integer FROM linked
$$;

CREATE TEMP TABLE native_offers_before_086 ON COMMIT DROP AS
    SELECT o.* FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
    JOIN current_event e ON e.id=c.event_id AND e.provider=c.venue
    WHERE c.venue IN ('kalshi','polymarket_us');
SELECT link_native_offers(NULL,NULL);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM native_offers_before_086 old LEFT JOIN current_offer new USING(contract_id)
        WHERE (old.price_value,old.facts,old.price_dependency,old.revision) IS DISTINCT FROM
              (new.price_value,new.facts,new.price_dependency,new.revision)) THEN
        RAISE EXCEPTION 'native_offer_migration_equivalence';
    END IF;
END
$$;

ALTER TABLE current_contract_storage ADD COLUMN independent_depth jsonb;
UPDATE current_contract_storage c SET independent_depth=d.depth
FROM (SELECT contract_id,jsonb_agg(jsonb_build_array(side,level,price_value,quantity_value,quantity_units)
                ORDER BY side,level) depth FROM current_depth GROUP BY contract_id) d WHERE c.id=d.contract_id;
ALTER TABLE current_depth RENAME TO independent_depth_before_086;
CREATE VIEW current_depth AS
    SELECT c.id AS contract_id,v->>0 AS side,(v->>1)::integer AS level,
        v->>2 AS price_value,v->>3 AS quantity_value,v->>4 AS quantity_units
    FROM current_contract_storage c CROSS JOIN LATERAL jsonb_array_elements(c.independent_depth) AS d(v)
    WHERE c.independent_depth IS NOT NULL;
DO $$
BEGIN
    IF EXISTS ((SELECT * FROM independent_depth_before_086 EXCEPT ALL SELECT * FROM current_depth)
        UNION ALL (SELECT * FROM current_depth EXCEPT ALL SELECT * FROM independent_depth_before_086)) THEN
        RAISE EXCEPTION 'independent_depth_migration_equivalence';
    END IF;
END
$$;
DROP TABLE independent_depth_before_086;
