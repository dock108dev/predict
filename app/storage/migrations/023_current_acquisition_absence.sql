-- Non-atomic listing absence is suspicion, never a provider withdrawal.
ALTER TABLE current_acquisition_market ADD COLUMN absent_since timestamptz;
ALTER TABLE current_acquisition_market ADD COLUMN missing_passes integer NOT NULL DEFAULT 0;
UPDATE current_acquisition_market SET withdrawn=false, disposition='suspected_absent',
    absent_since=observed_at, missing_passes=1 WHERE disposition='source_withdrawn';
