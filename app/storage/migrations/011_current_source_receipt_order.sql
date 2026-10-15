-- Source clocks govern freshness. Exact original quote/book receipt clocks
-- break ties; catalog capture ordering retains its existing retention clock.
-- NULL is a guarded transition: domain_migration backfills from retained JSON.
ALTER TABLE current_source_projection ADD COLUMN received_order numeric;
CREATE INDEX current_source_receipt_backfill ON current_source_projection(envelope_id)
 WHERE received_order IS NULL;
