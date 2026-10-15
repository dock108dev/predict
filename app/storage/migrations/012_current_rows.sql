-- Disposable working sports state. No references to protected account owners.
CREATE TABLE current_row_epoch (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), epoch text NOT NULL);
INSERT INTO current_row_epoch VALUES (true,md5(random()::text||clock_timestamp()::text));
CREATE TABLE current_event (
 id text PRIMARY KEY, provider text NOT NULL, native_event_id text NOT NULL,
 competition text NOT NULL, scheduled_start text NOT NULL, expires_order numeric NOT NULL,
 facts jsonb NOT NULL, revision text NOT NULL, UNIQUE(provider,native_event_id)
);
CREATE TABLE current_contract (
 id text PRIMARY KEY, event_id text NOT NULL REFERENCES current_event(id) ON DELETE CASCADE,
 venue text NOT NULL, native_market_id text NOT NULL, native_outcome_id text NOT NULL,
 native_side text NOT NULL, facts jsonb NOT NULL, revision text NOT NULL
);
CREATE INDEX current_contract_event ON current_contract(event_id);
CREATE TABLE current_offer (
 contract_id text PRIMARY KEY REFERENCES current_contract(id) ON DELETE CASCADE,
 price_value text NOT NULL, price_units text NOT NULL, quantity_units text NOT NULL,
 source_at text, source_order numeric, received_at text NOT NULL, received_order numeric NOT NULL,
 facts jsonb NOT NULL, revision text NOT NULL
);
CREATE TABLE current_depth (
 contract_id text NOT NULL REFERENCES current_contract(id) ON DELETE CASCADE,
 side text NOT NULL CHECK(side IN ('asks','bids')), level integer NOT NULL CHECK(level>=0),
 price_value text NOT NULL, quantity_value text NOT NULL, quantity_units text NOT NULL,
 PRIMARY KEY(contract_id,side,level)
);
CREATE TABLE current_source_status (
 venue text PRIMARY KEY, state jsonb NOT NULL, received_at text NOT NULL
);
CREATE TABLE current_refresh_scope (
 scope text PRIMARY KEY, source_order numeric NOT NULL, received_order numeric NOT NULL
);
ALTER TABLE current_event SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
ALTER TABLE current_contract SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
ALTER TABLE current_offer SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
ALTER TABLE current_depth SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
-- Native book headers preserve empty/missing sides. Exact levels are shared once.
CREATE TABLE current_native_book (
 venue text NOT NULL,event_id text NOT NULL REFERENCES current_event(id) ON DELETE CASCADE,
 native_market_id text NOT NULL,source_at text,source_order numeric,received_at text NOT NULL,received_order numeric NOT NULL,
 revision text NOT NULL,quantity_units text NOT NULL,state text NOT NULL,sync text NOT NULL,sequence text,
 outcomes jsonb NOT NULL,PRIMARY KEY(venue,event_id,native_market_id)
);
CREATE TABLE current_native_depth (
 venue text NOT NULL,event_id text NOT NULL,native_market_id text NOT NULL,native_outcome_id text NOT NULL,
 side text NOT NULL CHECK(side IN ('asks','bids')),level integer NOT NULL,
 price_value text NOT NULL,price_units text NOT NULL,quantity_value text NOT NULL,quantity_units text NOT NULL,
 PRIMARY KEY(venue,event_id,native_market_id,native_outcome_id,side,level),
 FOREIGN KEY(venue,event_id,native_market_id) REFERENCES current_native_book(venue,event_id,native_market_id) ON DELETE CASCADE
);
ALTER TABLE current_native_depth SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=50);
