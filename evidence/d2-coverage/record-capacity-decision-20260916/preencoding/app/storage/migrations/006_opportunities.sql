-- Additive E4 offline audits. Exact input timestamps and Decimal text in payloads.
CREATE TABLE opportunity_dependency (
 id text PRIMARY KEY, payload text NOT NULL, payload_sha256 text NOT NULL
);
CREATE TABLE opportunity_audit (
 id text PRIMARY KEY, estimate_id text NOT NULL REFERENCES fair_price(id),
 as_of timestamptz NOT NULL, evaluated_at timestamptz NOT NULL,
 version text NOT NULL, payload text NOT NULL, payload_sha256 text NOT NULL,
 CHECK (evaluated_at >= as_of)
);
CREATE INDEX opportunity_cutoff ON opportunity_audit(as_of,id);
CREATE TABLE opportunity_input (
 audit_id text NOT NULL REFERENCES opportunity_audit(id), kind text NOT NULL,
 dependency_id text NOT NULL REFERENCES opportunity_dependency(id),
 PRIMARY KEY(audit_id,kind)
);
CREATE TRIGGER immutable_opportunity_dependency BEFORE UPDATE OR DELETE ON opportunity_dependency FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_opportunity_audit BEFORE UPDATE OR DELETE ON opportunity_audit FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_opportunity_input BEFORE UPDATE OR DELETE ON opportunity_input FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
