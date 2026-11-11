-- A frame witnesses the observations present in one page, not absence.
CREATE TABLE current_sgo_event_frame (
    event_id text PRIMARY KEY,
    received_order numeric NOT NULL,
    expires_at timestamptz NOT NULL,
    payload_bytes integer NOT NULL,
    facts jsonb NOT NULL
);
CREATE INDEX current_sgo_event_frame_expiry ON current_sgo_event_frame (expires_at);
