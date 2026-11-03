-- A later dirty hint must not overtake already waiting refresh work merely
-- because its last successful visit was older. This queue is scheduling only.
CREATE SEQUENCE current_result_refresh_order;
ALTER TABLE current_result_work ADD COLUMN refresh_order bigint;
ALTER TABLE current_result_work ADD COLUMN refresh_visit_order bigint;
CREATE INDEX current_result_refresh_waiting ON current_result_work(refresh_order)
    WHERE refresh_order IS NOT NULL;
ALTER TABLE current_result_inventory ADD COLUMN superseded_at timestamptz;
ALTER TABLE current_result_inventory ADD COLUMN superseded_by jsonb;
