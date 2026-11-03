CREATE TABLE comparison_snapshot (
    id text PRIMARY KEY,
    captured_at timestamptz NOT NULL,
    inputs bytea NOT NULL,
    lease_until timestamptz NOT NULL DEFAULT now() + interval '2 hours'
);
CREATE TABLE comparison_snapshot_result (
    id text PRIMARY KEY,
    snapshot_id text NOT NULL REFERENCES comparison_snapshot(id) ON DELETE CASCADE,
    calculated_at timestamptz NOT NULL DEFAULT now(),
    assumptions jsonb NOT NULL,
    result bytea NOT NULL,
    lease_until timestamptz NOT NULL DEFAULT now() + interval '2 hours'
);
CREATE TABLE comparison_snapshot_head (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    result_id text NOT NULL REFERENCES comparison_snapshot_result(id)
);
