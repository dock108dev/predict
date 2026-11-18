-- Availability inferred only from repeated successful complete alternate scopes.
CREATE TABLE sgo_line_presence (
 quote_id text PRIMARY KEY, event_id text NOT NULL, bookmaker_id text NOT NULL,
 odd_id text NOT NULL, last_seen numeric NOT NULL, scope_received numeric NOT NULL,
 missing_since numeric, expired boolean NOT NULL DEFAULT false
);
CREATE INDEX sgo_line_presence_scope ON sgo_line_presence(event_id,bookmaker_id,odd_id);
CREATE OR REPLACE VIEW current_sgo_reference AS
 SELECT q.id,q.event_id,q.bookmaker_id,q.source_order,q.received_order,q.expires_at,q.revision,q.facts
 FROM sgo_quote_revision q WHERE q.is_current
 AND NOT EXISTS(SELECT 1 FROM sgo_line_presence p WHERE p.quote_id=q.id AND p.expired);
CREATE OR REPLACE VIEW current_offer AS
    SELECT o.contract_id,COALESCE(o.price_value,q.facts->>'price_american',a.levels->0->>0) AS price_value,
        o.price_units,o.quantity_units,o.source_at,o.source_order,o.received_at,o.received_order,
        CASE WHEN EXISTS(SELECT 1 FROM sgo_line_presence lp WHERE lp.quote_id=o.sgo_quote_id AND lp.expired) THEN jsonb_set(jsonb_set(o.facts,'{original,value}',q.facts->'price_american'),'{state}','"unavailable"'::jsonb) WHEN o.sgo_quote_id IS NOT NULL THEN jsonb_set(o.facts,'{original,value}',q.facts->'price_american')
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


INSERT INTO sgo_line_presence(quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received)
 SELECT id,event_id,bookmaker_id,facts->>'odd_id',received_order,received_order
 FROM sgo_quote_revision WHERE is_current;
