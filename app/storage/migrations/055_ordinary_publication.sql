-- Automatic revisions are replaceable; only explicit readers retain evidence.
ALTER TABLE comparison_snapshot ADD COLUMN automatic boolean NOT NULL DEFAULT false;
ALTER TABLE comparison_snapshot_result ADD COLUMN automatic boolean NOT NULL DEFAULT false;
CREATE TABLE comparison_live_head (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 generation bigint NOT NULL DEFAULT 0,
 result_id text REFERENCES comparison_snapshot_result(id),
 facts jsonb NOT NULL DEFAULT '{}'
);
INSERT INTO comparison_live_head(singleton) VALUES(true);
