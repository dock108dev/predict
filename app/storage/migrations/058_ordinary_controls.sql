CREATE TABLE comparison_live_settings (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 assumptions jsonb NOT NULL
);
CREATE TABLE comparison_live_lease (
 id text PRIMARY KEY,
 result_id text NOT NULL REFERENCES comparison_snapshot_result(id),
 expires_at timestamptz NOT NULL
);
