-- Preserve the effective live settings at the boundary. Saved/manual
-- assumptions remain bound to their immutable historical results.
CREATE TABLE comparison_policy_revision (
    id text PRIMARY KEY,
    assumptions jsonb NOT NULL CHECK (jsonb_typeof(assumptions) = 'object'),
    active boolean NOT NULL DEFAULT false,
    CHECK (assumptions->>'revision' IS NOT DISTINCT FROM id)
);
CREATE UNIQUE INDEX comparison_policy_active ON comparison_policy_revision (active) WHERE active;
WITH previous AS (
    SELECT assumptions FROM comparison_live_settings WHERE singleton
    UNION ALL
    SELECT r.assumptions FROM comparison_snapshot_head h
    JOIN comparison_snapshot_result r ON r.id=h.result_id
    WHERE NOT EXISTS (SELECT 1 FROM comparison_live_settings WHERE singleton)
)
INSERT INTO comparison_policy_revision (id, assumptions, active)
    SELECT assumptions->>'revision', assumptions, true FROM previous
    WHERE jsonb_typeof(assumptions->'revision')='string';
-- Refuse the cutover if an existing settings record had no revision.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM comparison_policy_revision)
        AND (EXISTS (SELECT 1 FROM comparison_live_settings)
             OR EXISTS (SELECT 1 FROM comparison_snapshot_head)) THEN
        RAISE EXCEPTION 'comparison_policy_migration_missing_revision';
    END IF;
END $$;
DROP TABLE comparison_live_settings;
