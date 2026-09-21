-- E2 offline reference history. No fair_price or execution tables.
CREATE TABLE reference_source_revision (
 id text PRIMARY KEY, provider text NOT NULL, book text NOT NULL,
 effective_at timestamptz NOT NULL, known_at timestamptz NOT NULL,
 payload text NOT NULL, payload_sha256 text NOT NULL,
 CHECK(provider = 'the_odds_api' AND book = 'pinnacle')
);
CREATE TABLE reference_receipt (
 id text PRIMARY KEY, session_id text NOT NULL REFERENCES capture_session(id),
 provider text NOT NULL DEFAULT 'the_odds_api', native_event_id text NOT NULL,
 received_at timestamptz NOT NULL, raw_hash text NOT NULL REFERENCES artifact(hash),
 payload text NOT NULL, payload_sha256 text NOT NULL,
 UNIQUE(id,session_id)
);
CREATE INDEX reference_receipt_time ON reference_receipt(provider,native_event_id,received_at,id);
CREATE TABLE reference_quote_revision (
 id text PRIMARY KEY, session_id text NOT NULL,
 receipt_id text NOT NULL, source_id text NOT NULL REFERENCES reference_source_revision(id),
 known_at timestamptz NOT NULL, effective_at timestamptz NOT NULL,
 payload text NOT NULL, payload_sha256 text NOT NULL,
 FOREIGN KEY(receipt_id,session_id) REFERENCES reference_receipt(id,session_id)
);
CREATE INDEX reference_enrichment_time ON reference_quote_revision(receipt_id,known_at,id);
CREATE TABLE reference_gap (
 id text PRIMARY KEY, session_id text NOT NULL REFERENCES capture_session(id),
 receipt_id text, prior_gap_id text REFERENCES reference_gap(id),
 detected_at timestamptz NOT NULL, payload text NOT NULL, payload_sha256 text NOT NULL,
 FOREIGN KEY(receipt_id,session_id) REFERENCES reference_receipt(id,session_id)
);
CREATE INDEX reference_gap_time ON reference_gap(session_id,detected_at,id);
CREATE FUNCTION reject_reference_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable reference history'; END IF;
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'immutable reference history'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_reference_source BEFORE UPDATE OR DELETE ON reference_source_revision FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_reference_receipt BEFORE UPDATE OR DELETE ON reference_receipt FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_reference_quote BEFORE UPDATE OR DELETE ON reference_quote_revision FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_reference_gap BEFORE UPDATE OR DELETE ON reference_gap FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
