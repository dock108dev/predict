-- Viewing/collection intent is independent of protected source Stop and budgets.
CREATE TABLE activity_mode (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 mode text NOT NULL DEFAULT 'monitor' CHECK(mode IN ('monitor','live')),
 settings jsonb NOT NULL,
 revision bigint NOT NULL DEFAULT 1,
 last_activity_at timestamptz,
 live_until timestamptz,
 reason text NOT NULL DEFAULT 'default',
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO activity_mode(singleton,settings) VALUES(true,
 '{"monitor_interval_seconds":1800,"monitor_horizon_seconds":86400,"live_interval_seconds":60,"live_window_seconds":3600,"inactivity_seconds":900}');
CREATE TABLE activity_collection_run (
 id text PRIMARY KEY,kind text NOT NULL CHECK(kind IN ('monitor','live')),
 started_at timestamptz NOT NULL,scope_start_at timestamptz NOT NULL,
 scope_end_at timestamptz,settings_revision bigint NOT NULL,
 state text NOT NULL DEFAULT 'running' CHECK(state IN ('running','budget_delayed','partial','complete','failed')),
 completed_at timestamptz,event_count integer NOT NULL DEFAULT 0,
 reason text,progress jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX activity_collection_run_latest ON activity_collection_run(kind,started_at DESC);

-- Mode status polls must not repeatedly scan retained staged bodies.
CREATE INDEX odds_archive_stage_received_at ON odds_archive_stage(received_at);
