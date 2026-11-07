-- Reuse bounded matching neighborhoods; one current pointer per component.
CREATE TABLE comparison_live_component (
 id text PRIMARY KEY,
 result_id text NOT NULL REFERENCES comparison_snapshot_result(id),
 facts jsonb NOT NULL
);
-- Composite evidence retains its exact member revisions, without copying inputs.
CREATE TABLE comparison_live_member (
 result_id text NOT NULL REFERENCES comparison_snapshot_result(id) ON DELETE CASCADE,
 member_id text NOT NULL REFERENCES comparison_snapshot_result(id),
 PRIMARY KEY(result_id,member_id)
);
