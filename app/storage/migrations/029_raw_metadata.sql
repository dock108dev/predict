-- Reusable small list metadata avoids detoasting every provider description when
-- sorting/filtering one raw page. Bodies and books remain in their owning tables.
ALTER TABLE current_native_market_recovery ADD COLUMN display_metadata jsonb
 GENERATED ALWAYS AS (jsonb_set(jsonb_set(jsonb_set('{}'::jsonb,'{title}',COALESCE(metadata->'title','null'::jsonb)),'{period}',COALESCE(metadata->'period','null'::jsonb)),'{sides}',COALESCE(metadata->'sides','null'::jsonb))) STORED;
ALTER TABLE current_acquisition_market ADD COLUMN display_title text GENERATED ALWAYS AS (metadata->>'title') STORED;
ALTER TABLE current_acquisition_market ADD COLUMN display_line text GENERATED ALWAYS AS (COALESCE(metadata->>'line',metadata->>'floor_strike')) STORED;
