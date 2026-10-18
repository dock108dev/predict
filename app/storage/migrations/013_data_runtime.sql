-- Compact cross-process lifecycle state. Protected account/financial owners are untouched.
CREATE TABLE data_runtime (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 runtime_id text NOT NULL, owner_pid integer NOT NULL,
 started_at timestamptz NOT NULL, heartbeat_at timestamptz NOT NULL,
 state text NOT NULL CHECK(state IN ('starting','running','stopping','stopped','failed')),
 config jsonb NOT NULL, source_status jsonb NOT NULL, dispatch boolean NOT NULL,
 status jsonb NOT NULL, revision bigint NOT NULL DEFAULT 1, fingerprint text NOT NULL,
 paused_sources jsonb NOT NULL DEFAULT '[]', global_stopped boolean NOT NULL DEFAULT false
);
CREATE TABLE data_runtime_command (
 id text PRIMARY KEY, runtime_id text NOT NULL, action text NOT NULL,
 body jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL, state text NOT NULL DEFAULT 'pending'
   CHECK(state IN ('pending','acknowledged','failed')),
 acknowledgment jsonb
);
CREATE INDEX data_runtime_command_pending ON data_runtime_command(created_at) WHERE state='pending';
ALTER TABLE data_runtime_command SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
