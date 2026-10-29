CREATE TABLE current_acquisition_alternate (
    sport text NOT NULL,
    event_id text NOT NULL,
    received_at timestamptz NOT NULL,
    cycle_id text NOT NULL,
    receipt_sha256 text NOT NULL,
    disposition text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY(sport,event_id)
);
