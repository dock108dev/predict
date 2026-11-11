-- Current provider observations only. A cursor walk does not authorize deletion.
CREATE TABLE current_sgo_reference (
    id text PRIMARY KEY,
    event_id text NOT NULL,
    bookmaker_id text NOT NULL,
    source_order numeric,
    received_order numeric NOT NULL,
    expires_at timestamptz NOT NULL,
    revision text NOT NULL,
    facts jsonb NOT NULL
);
CREATE INDEX current_sgo_reference_expiry ON current_sgo_reference (expires_at);
CREATE INDEX current_sgo_reference_event ON current_sgo_reference (event_id, id);
