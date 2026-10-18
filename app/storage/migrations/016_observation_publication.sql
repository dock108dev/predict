-- Observation publication does not imply a successful financial calculation.
ALTER TABLE latest_board ALTER COLUMN calculated_at DROP NOT NULL;
