-- Metadata-only cutover: historical rows remain byte-for-byte intact. New
-- receipts may reuse unchanged depth and wire TOAST values independently.
ALTER TABLE current_acquisition_image RENAME TO current_acquisition_image_parts;
ALTER TABLE current_acquisition_image_parts ADD COLUMN depth_payload jsonb, ADD COLUMN wire_payload jsonb;
CREATE VIEW current_acquisition_image AS SELECT source,event_id,market_id,received_at,disposition,
 CASE WHEN wire_payload IS NULL THEN image ELSE jsonb_set(image,'{raw,json_text}',wire_payload) END
 || CASE WHEN depth_payload IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('outcomes',depth_payload) END AS image,
 runtime_id,connection_generation,census_generation,persisted_at FROM current_acquisition_image_parts;
-- No default/backfill: NULL means a self-contained legacy recovery value.
ALTER TABLE current_native_market_recovery ADD COLUMN receipt_fields jsonb;
