-- Immutable compact projection, once per exact member; roots contain only IDs.
-- The member FK and existing root/member/selection graph own its lifetime.
CREATE TABLE comparison_live_read_fragment (
 member_id text PRIMARY KEY REFERENCES comparison_snapshot_result(id) ON DELETE CASCADE,
 summary jsonb NOT NULL,
 content bytea NOT NULL
);
ALTER TABLE comparison_live_read_fragment SET (
 autovacuum_vacuum_scale_factor=0.02, toast.autovacuum_vacuum_scale_factor=0.02
);
