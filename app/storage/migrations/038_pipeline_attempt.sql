-- One replaceable attempt summary per live event and branch; expiry cascades.
-- No book bodies, private responses, credentials or unbounded attempt log.
CREATE TABLE current_pipeline_attempt (
    event_id text NOT NULL REFERENCES current_event(id) ON DELETE CASCADE,
    branch text NOT NULL CHECK(branch IN ('raw_grid','metrics')),
    first_attempt timestamptz NOT NULL,
    last_attempt timestamptz NOT NULL,
    attempts bigint NOT NULL,
    disposition text NOT NULL,
    reason text NOT NULL,
    elapsed_ms double precision NOT NULL,
    engine text NOT NULL,
    facts jsonb NOT NULL,
    PRIMARY KEY(event_id,branch)
);
