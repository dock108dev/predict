-- Automatic compressed revisions replace frequently while the parent table has
-- few rows. PostgreSQL's default 50-row threshold delays TOAST reuse too long.
ALTER TABLE comparison_snapshot SET (
 autovacuum_vacuum_threshold=5,autovacuum_vacuum_scale_factor=0.01,
 toast.autovacuum_vacuum_threshold=5,toast.autovacuum_vacuum_scale_factor=0.01,
 autovacuum_vacuum_cost_delay=0
);
ALTER TABLE comparison_snapshot_result SET (
 autovacuum_vacuum_threshold=5,autovacuum_vacuum_scale_factor=0.01,
 toast.autovacuum_vacuum_threshold=5,toast.autovacuum_vacuum_scale_factor=0.01,
 autovacuum_vacuum_cost_delay=0
);
