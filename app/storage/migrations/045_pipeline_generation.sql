-- Compact lifecycle evidence; no raw bodies or credentials. Terminal history is
-- bounded by the publisher, while unfinished generations remain diagnosable.
CREATE TABLE pipeline_generation (
    id text PRIMARY KEY,
    game_key text NOT NULL,
    engine text NOT NULL,
    policy text NOT NULL,
    dependency_revision text NOT NULL,
    events jsonb NOT NULL,
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_attempt timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    published_at timestamptz,
    attempts bigint NOT NULL DEFAULT 1,
    calculations bigint NOT NULL DEFAULT 0,
    reuses bigint NOT NULL DEFAULT 0,
    commits bigint NOT NULL DEFAULT 0,
    disposition text NOT NULL DEFAULT 'eligible_pending',
    reason text,
    facts jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX pipeline_generation_game ON pipeline_generation(game_key,last_attempt);
