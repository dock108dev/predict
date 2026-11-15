-- Keep the newest exact closure receipt separate from the original quote.
-- NULL means that the original receipt is the only retained observation.
-- Every existing row starts NULL. NOT VALID enforces the invariant for
-- subsequent writes without scanning past revisions under the DDL lock.
SET LOCAL lock_timeout = '5s';
ALTER TABLE sgo_quote_revision ADD COLUMN closure_received_order numeric;
ALTER TABLE sgo_quote_revision ADD CONSTRAINT sgo_closure_receipt_order
    CHECK (closure_received_order IS NULL OR (
        source_order IS NOT NULL AND closure_received_order >= source_order
        AND closure_received_order >= received_order
    )) NOT VALID;
