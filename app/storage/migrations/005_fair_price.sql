-- E3 additive immutable synthetic estimates; exact timestamp text stays in payload.
CREATE TABLE fair_price (
 id text PRIMARY KEY, target_venue text NOT NULL,
 as_of timestamptz NOT NULL, estimated_at timestamptz NOT NULL,
 method text NOT NULL, policy_version text NOT NULL,
 payload text NOT NULL, payload_sha256 text NOT NULL,
 CHECK (estimated_at >= as_of), CHECK (target_venue IN ('kalshi','polymarket_us'))
);
CREATE INDEX fair_price_cutoff ON fair_price(target_venue,as_of,id);
CREATE TABLE fair_price_input (
 estimate_id text NOT NULL REFERENCES fair_price(id),
 receipt_id text NOT NULL REFERENCES reference_receipt(id),
 enrichment_id text REFERENCES reference_quote_revision(id),
 source_id text REFERENCES reference_source_revision(id),
 included boolean NOT NULL,
 payload text NOT NULL, payload_sha256 text NOT NULL,
 PRIMARY KEY(estimate_id,receipt_id)
);
CREATE TRIGGER immutable_fair_price BEFORE UPDATE OR DELETE ON fair_price FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_fair_price_input BEFORE UPDATE OR DELETE ON fair_price_input FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
