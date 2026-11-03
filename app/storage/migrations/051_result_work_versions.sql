-- One replaceable pending input hint per discovered dependency unit. A visit is
-- a fairness claim, never a completion acknowledgement. No receipt/job history.
ALTER TABLE current_result_work ADD COLUMN pending_version bigint NOT NULL DEFAULT 1;
ALTER TABLE current_result_work ADD COLUMN acknowledged_version bigint NOT NULL DEFAULT 0;
ALTER TABLE current_result_work ADD COLUMN claimed_version bigint;
ALTER TABLE current_result_work ADD COLUMN input_hint text;
ALTER TABLE current_result_work ADD COLUMN dirty_since timestamptz DEFAULT clock_timestamp();
ALTER TABLE current_result_work ADD CONSTRAINT result_work_versions CHECK (
    acknowledged_version <= pending_version AND
    (claimed_version IS NULL OR claimed_version <= pending_version));
