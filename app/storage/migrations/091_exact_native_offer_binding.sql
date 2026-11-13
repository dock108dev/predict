-- Bind inline offers to a uniquely evidenced book, including a retained revision.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(901095);

CREATE OR REPLACE FUNCTION link_native_offers(offer_ids text[], book_ids text[])
RETURNS integer LANGUAGE sql AS $$
    WITH exact AS (
        SELECT o.contract_id,b.id AS book_id,p.native_outcome_id AS bid_outcome_id
        FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id AND e.provider=c.venue
        JOIN native_book_revision b ON (b.venue,b.event_id,b.native_market_id)=(c.venue,c.event_id,c.native_market_id)
            AND b.received_at=o.received_at
            AND (b.source_at,b.confirmation) IS NOT DISTINCT FROM (o.source_at,o.facts->'book_confirmation')
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
            AND c.venue IN ('kalshi','polymarket_us')
            AND (offer_ids IS NULL OR o.contract_id=ANY(offer_ids))
            AND (book_ids IS NULL OR EXISTS (
                SELECT 1 FROM native_book_revision wanted WHERE wanted.id=ANY(book_ids)
                AND (wanted.venue,wanted.event_id,wanted.native_market_id,wanted.received_at)=
                    (b.venue,b.event_id,b.native_market_id,b.received_at)
            ))
            AND o.facts#>>'{source,native_outcome_id}'=c.native_outcome_id
            AND o.facts#>>'{source,provider}'=e.provider
            AND o.facts#>>'{source,native_event_id}'=e.native_event_id
            AND o.facts#>>'{source,native_market_id}'=c.native_market_id
            AND (o.price_value,o.price_units,o.quantity_units)=(a.levels->0->>0,a.levels->0->>1,a.levels->0->>3)
            AND o.facts#>>'{original,value}'=o.price_value
            AND ((p.native_outcome_id IS NULL AND o.facts#>'{original,native_value}' IS NULL
                AND o.facts#>>'{original,transformation}' IS DISTINCT FROM 'one_minus_native_bid')
                OR (p.native_outcome_id IS NOT NULL AND jsonb_array_length(b.outcomes)=2))
    ), unique_matches AS (
        SELECT contract_id,min(book_id) AS book_id,min(bid_outcome_id) AS bid_outcome_id
        FROM exact GROUP BY contract_id HAVING count(*)=1
    ), linked AS (
        UPDATE current_offer_storage o SET native_book_id=x.book_id,native_bid_outcome_id=x.bid_outcome_id,
            price_value=NULL,facts=o.facts#-'{original,value}'#-'{original,native_value}'
        FROM unique_matches x WHERE x.contract_id=o.contract_id
            AND (book_ids IS NULL OR x.book_id=ANY(book_ids))
        RETURNING 1
    ) SELECT count(*)::integer FROM linked
$$;

CREATE TEMP TABLE native_offers_before_091 ON COMMIT DROP AS
    SELECT o.contract_id,sha256(convert_to(jsonb_build_array(o.price_value,o.facts,o.price_dependency,o.revision)::text,'UTF8')) AS proof
    FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
    JOIN current_event e ON e.id=c.event_id AND e.provider=c.venue
    WHERE c.venue IN ('kalshi','polymarket_us') AND o.native_book_id IS NULL;
SELECT link_native_offers(NULL,NULL);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM native_offers_before_091 old LEFT JOIN current_offer o USING(contract_id)
        WHERE old.proof IS DISTINCT FROM
            sha256(convert_to(jsonb_build_array(o.price_value,o.facts,o.price_dependency,o.revision)::text,'UTF8'))) THEN
        RAISE EXCEPTION 'native_offer_binding_migration_equivalence';
    END IF;
END
$$;
