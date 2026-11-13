-- Versioned settings used by new live and manual results. Historical results
-- keep their complete embedded assumptions, including originally unknown IDs.
ALTER TABLE comparison_snapshot_result ADD COLUMN settings_revision text
    REFERENCES comparison_policy_revision(id);
