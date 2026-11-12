-- Bounded, best-effort audit witnesses. Never used as current price authority.
CREATE TABLE current_sgo_history (
    kind text NOT NULL CHECK (kind IN ('reference','frame')),
    identity text NOT NULL,
    revision text NOT NULL,
    event_id text NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    facts jsonb NOT NULL,
    PRIMARY KEY (kind, identity, revision)
);
CREATE INDEX current_sgo_history_expiry ON current_sgo_history (archived_at);
CREATE INDEX current_sgo_history_event ON current_sgo_history (event_id, kind, archived_at);
CREATE TABLE current_sgo_history_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    recorded bigint NOT NULL DEFAULT 0,
    skipped_capacity bigint NOT NULL DEFAULT 0,
    skipped_runway bigint NOT NULL DEFAULT 0
);
INSERT INTO current_sgo_history_state (singleton) VALUES (true);
