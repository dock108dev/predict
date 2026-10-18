-- Replaceable shared calculation state; never a quote or report history.
CREATE TABLE scanner_latest (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 runtime_id text NOT NULL, runtime_revision bigint NOT NULL,
 dependency_revision text NOT NULL, publication bigint NOT NULL,
 published_at timestamptz NOT NULL, payload jsonb NOT NULL,
 CHECK (octet_length(payload::text)<=33554432)
);
ALTER TABLE scanner_latest SET (autovacuum_vacuum_scale_factor=0.01,autovacuum_vacuum_threshold=10,
 toast.autovacuum_vacuum_scale_factor=0.01,toast.autovacuum_vacuum_threshold=10);
