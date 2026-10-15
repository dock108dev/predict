-- Exact domain-owned anchors; compact revision payloads refer to immutable bases.
CREATE TABLE current_domain_anchor (
 id bytea PRIMARY KEY CHECK(octet_length(id)=32),
 logical_bytes integer NOT NULL CHECK(logical_bytes BETWEEN 0 AND 8388608),
 content bytea NOT NULL
);
CREATE TABLE current_domain_head (
 scope bytea PRIMARY KEY CHECK(octet_length(scope)=32),
 anchor_id bytea NOT NULL REFERENCES current_domain_anchor(id)
);
CREATE TABLE current_calculation_attempt (
 id bigserial PRIMARY KEY, snapshot_id text NOT NULL REFERENCES current_game_snapshot(id),
 result_id text NOT NULL REFERENCES current_game_result(id),
 attempted_at timestamptz NOT NULL, reused boolean NOT NULL, published boolean NOT NULL
);
CREATE INDEX current_calculation_snapshot ON current_game_result(snapshot_id,calculated_at,id);
CREATE TRIGGER immutable_current_domain_anchor BEFORE UPDATE OR DELETE ON current_domain_anchor
 FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_current_calculation_attempt BEFORE UPDATE OR DELETE ON current_calculation_attempt
 FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
