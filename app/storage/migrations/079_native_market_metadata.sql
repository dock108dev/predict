-- The two current owners reference an exact immutable source body. Legacy
-- inline rows remain readable until their next bounded rewrite or replacement.
CREATE TABLE current_native_market_body (
    id bytea PRIMARY KEY CHECK (octet_length(id) = 32),
    body text NOT NULL CHECK (jsonb_typeof(body::jsonb) = 'object'),
    CHECK (sha256(convert_to(body, 'UTF8')) = id)
);
CREATE TRIGGER immutable_native_market_body BEFORE UPDATE ON current_native_market_body
    FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();

ALTER TABLE current_acquisition_market ADD COLUMN metadata_id bytea
    REFERENCES current_native_market_body(id);
ALTER TABLE current_native_market_recovery ADD COLUMN metadata_id bytea
    REFERENCES current_native_market_body(id);
CREATE INDEX current_acquisition_market_body ON current_acquisition_market(metadata_id)
    WHERE metadata_id IS NOT NULL;
CREATE INDEX current_native_market_recovery_body ON current_native_market_recovery(metadata_id)
    WHERE metadata_id IS NOT NULL;
