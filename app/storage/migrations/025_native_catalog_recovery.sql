CREATE TABLE current_native_catalog_recovery (
 source text PRIMARY KEY, scope text NOT NULL, saved_at timestamptz NOT NULL DEFAULT now(), header jsonb NOT NULL
);
CREATE TABLE current_native_market_recovery (
 source text NOT NULL REFERENCES current_native_catalog_recovery(source) ON DELETE CASCADE,
 market_id text NOT NULL, metadata jsonb NOT NULL, parsed jsonb,
 PRIMARY KEY(source,market_id)
);
