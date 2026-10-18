-- One replaceable bounded coverage cohort. No receipt, quota or account history.
CREATE TABLE coverage_latest (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 captured_at text NOT NULL,
 revision text NOT NULL,
 facts jsonb NOT NULL,
 CHECK(octet_length(facts::text)<=8388608)
);
ALTER TABLE coverage_latest SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=10);
