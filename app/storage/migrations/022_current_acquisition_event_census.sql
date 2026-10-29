CREATE TABLE current_acquisition_event_census (
    sport text PRIMARY KEY,
    cycle_id text NOT NULL,
    received_at timestamptz NOT NULL,
    receipt_sha256 text NOT NULL,
    payload jsonb NOT NULL
);
