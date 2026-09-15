-- A depth audit alone does not contain the whole matcher report. Preserve unknown.
ALTER TABLE candidate_observation ALTER COLUMN structural DROP NOT NULL;
