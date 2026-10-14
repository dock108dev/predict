-- Exact fractional source-clock ordering, independent of timestamptz precision.
ALTER TABLE current_source_projection ADD COLUMN observed_order numeric;
UPDATE current_source_projection SET observed_order=extract(epoch FROM observed_at);
ALTER TABLE current_source_projection ALTER COLUMN observed_order SET NOT NULL;
