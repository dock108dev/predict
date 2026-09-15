CREATE TABLE artifact (
 hash text PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{64}$'),
 content bytea NOT NULL, kind text NOT NULL CHECK (kind IN ('raw','tree'))
);
CREATE TABLE artifact_edge (
 parent text REFERENCES artifact(hash), child text REFERENCES artifact(hash),
 PRIMARY KEY(parent,child)
);
CREATE TABLE capture_session (
 id text PRIMARY KEY, environment text NOT NULL,
 evidence_class text NOT NULL CHECK(evidence_class IN ('historical','synthetic','current')),
 started_at timestamptz NOT NULL, ended_at timestamptz,
 state text NOT NULL CHECK(state IN ('running','complete','failed','interrupted')),
 config jsonb NOT NULL, provenance text NOT NULL,
 CHECK(evidence_class != 'synthetic' OR environment = 'synthetic')
);
CREATE TABLE receipt (
 session_id text REFERENCES capture_session(id), id text,
 received_at timestamptz NOT NULL, received_text text NOT NULL, source_time_text text,
 venue text NOT NULL, event_id text NOT NULL, market_id text NOT NULL,
 source text NOT NULL, raw_hash text NOT NULL REFERENCES artifact(hash),
 normalized_hash text NOT NULL REFERENCES artifact(hash),
 bbo_hash text NOT NULL REFERENCES artifact(hash), changed boolean NOT NULL,
 snapshot_reason text NOT NULL, PRIMARY KEY(session_id,id)
);
CREATE INDEX receipt_market_time ON receipt(session_id,venue,market_id,received_at);
CREATE TABLE quote_observation (
 session_id text, receipt_id text, side text,
 ask numeric, ask_size numeric, bid numeric, bid_size numeric,
 unit text, state text NOT NULL, PRIMARY KEY(session_id,receipt_id,side),
 FOREIGN KEY(session_id,receipt_id) REFERENCES receipt(session_id,id),
 CHECK(ask BETWEEN 0 AND 1), CHECK(bid BETWEEN 0 AND 1), CHECK(ask_size >= 0), CHECK(bid_size >= 0)
);
CREATE TABLE metadata_version (
 session_id text REFERENCES capture_session(id), kind text, native_key text, hash text REFERENCES artifact(hash),
 PRIMARY KEY(session_id,kind,native_key,hash)
);
CREATE TABLE calculation (
 session_id text REFERENCES capture_session(id), id text, engine text NOT NULL,
 observed_at timestamptz NOT NULL, observed_text text NOT NULL,
 audit_hash text NOT NULL REFERENCES artifact(hash), PRIMARY KEY(session_id,id)
);
CREATE INDEX calculation_time ON calculation(session_id,engine,observed_at);
CREATE TABLE calculation_receipt (
 session_id text, calculation_id text, receipt_id text,
 PRIMARY KEY(session_id,calculation_id,receipt_id),
 FOREIGN KEY(session_id,calculation_id) REFERENCES calculation(session_id,id),
 FOREIGN KEY(session_id,receipt_id) REFERENCES receipt(session_id,id)
);
CREATE TABLE candidate_observation (
 session_id text, calculation_id text, candidate_id text,
 observed_at timestamptz NOT NULL, engine text NOT NULL,
 structural boolean NOT NULL, conditional_positive boolean NOT NULL, qualified boolean NOT NULL,
 state text NOT NULL, reasons jsonb NOT NULL, liquidity_families jsonb NOT NULL,
 result_hash text NOT NULL REFERENCES artifact(hash), changed boolean NOT NULL,
 PRIMARY KEY(session_id,calculation_id,candidate_id),
 FOREIGN KEY(session_id,calculation_id) REFERENCES calculation(session_id,id)
);
CREATE INDEX candidate_history ON candidate_observation(session_id,candidate_id,engine,observed_at);
CREATE INDEX candidate_classification ON candidate_observation(session_id,state,observed_at);
CREATE TABLE coverage_event (
 session_id text REFERENCES capture_session(id), id text,
 observed_at timestamptz NOT NULL, original_time text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('gap','disconnect','failure','restart','shutdown','limit','coverage')),
 detail jsonb NOT NULL, PRIMARY KEY(session_id,id)
);
CREATE INDEX coverage_time ON coverage_event(session_id,observed_at);
