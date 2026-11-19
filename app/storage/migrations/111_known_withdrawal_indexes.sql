-- Sparse negative authority must not fetch/decompress every positive witness.
-- Current-head identity is unique (078); missing or NULL flags stay unknown.
CREATE INDEX sgo_quote_known_unavailable ON public.sgo_quote_revision(id)
 WHERE is_current AND (facts->'available'='false'::jsonb
                    OR facts->'provider_available'='false'::jsonb);
CREATE INDEX sgo_line_known_expired ON public.sgo_line_presence(quote_id) WHERE expired;
CREATE INDEX current_offer_known_unavailable ON public.current_offer_storage(contract_id)
 WHERE facts->>'state'='unavailable';
DO $$
DECLARE s text;
BEGIN
 FOREACH s IN ARRAY ARRAY['pregame_monitor','pregame_live','pregame_combined'] LOOP
  EXECUTE format('CREATE INDEX %I ON %I.sgo_line_presence(quote_id) WHERE expired',
                 s||'_line_expired',s);
 END LOOP;
END $$;
