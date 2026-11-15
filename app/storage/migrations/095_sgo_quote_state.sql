-- Older writers applied the legacy venue transport state to SGO observations.
-- Recover availability from the exact original quote, leaving its clocks and
-- read-time controls intact. Later explicit closures still take precedence.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(901095);

UPDATE current_offer_storage o
SET facts=jsonb_set(o.facts,'{state}','"available"'::jsonb),
    revision=encode(sha256(convert_to(o.revision||':sgo_quote_available','UTF8')),'hex')
FROM current_contract c
JOIN current_event e ON e.id=c.event_id
JOIN sgo_quote_revision q ON q.event_id=e.native_event_id
    AND q.bookmaker_id=coalesce(c.facts#>>'{comparison_source_metadata,provider_bookmaker_id}',c.venue)
    AND q.facts->>'odd_id'=c.native_outcome_id
WHERE e.provider='sportsgameodds'
  AND o.contract_id=c.id
  AND (o.sgo_quote_id,o.sgo_quote_revision)=(q.id,q.revision)
  AND o.facts->>'state'<>'available'
  AND o.facts#>>'{source,provider}'=e.provider
  AND o.facts#>>'{source,native_event_id}'=e.native_event_id
  AND q.facts->'available'='true'::jsonb
  AND q.facts->>'price_american' IS NOT NULL
  AND q.facts->>'source_at'=o.source_at
  AND q.source_order=o.source_order
  AND o.source_order<=o.received_order
  AND (q.facts->>'line')::numeric IS NOT DISTINCT FROM (o.facts#>>'{source,native_line}')::numeric
  AND NOT EXISTS (
      SELECT 1 FROM sgo_quote_revision successor
      WHERE successor.id=q.id AND successor.is_current
        AND successor.facts->'available'='false'::jsonb
        AND (successor.facts->'provider_available'='false'::jsonb
             OR successor.facts->>'price_american' IS NOT NULL)
        AND successor.source_order<=successor.received_order
        AND (successor.source_order>o.source_order OR
             (successor.source_order=o.source_order AND successor.received_order>=o.received_order))
  );

-- An older page could have accepted the exact price-less closure without a
-- normalized replacement offer. Apply that already committed closure now.
UPDATE current_offer_storage o
SET facts=jsonb_set(o.facts,'{state}','"unavailable"'::jsonb),
    revision=encode(sha256(convert_to(o.revision||closure.revision,'UTF8')),'hex')
FROM sgo_quote_revision closure
WHERE closure.is_current AND o.sgo_quote_id=closure.id
  AND o.facts#>>'{source,provider}'='sportsgameodds'
  AND o.facts->>'state'='available' AND closure.facts->'available'='false'::jsonb
  AND (closure.facts->'provider_available'='false'::jsonb
       OR closure.facts->>'price_american' IS NOT NULL)
  AND closure.source_order<=closure.received_order
  AND (closure.source_order>o.source_order OR
       (closure.source_order=o.source_order AND closure.received_order>=o.received_order));
