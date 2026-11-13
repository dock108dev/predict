-- Replaceable official catalog observations used by exact SGO venue bindings.
CREATE TABLE current_sgo_native_catalog (
    event_id text PRIMARY KEY,
    observed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revision text NOT NULL,
    facts jsonb NOT NULL
);
CREATE INDEX current_sgo_native_catalog_expiry ON current_sgo_native_catalog (expires_at);
