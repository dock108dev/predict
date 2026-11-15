-- The optional shadow recorder writes only within admitted source transactions.
-- Export claims own immutable membership until a remote read-back succeeds.
CREATE TABLE odds_archive_head (
    identity bytea PRIMARY KEY CHECK (octet_length(identity)=32),
    material bytea NOT NULL CHECK (octet_length(material)=32),
    expires_at timestamptz NOT NULL
);
CREATE INDEX odds_archive_head_expiry ON odds_archive_head(expires_at);
ALTER TABLE odds_archive_head SET (fillfactor=80, autovacuum_vacuum_scale_factor=0.05);

CREATE TABLE odds_archive_batch (
    feed text NOT NULL,
    receipt_day date NOT NULL,
    id text PRIMARY KEY,
    claimed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE odds_archive_stage (
    id bytea PRIMARY KEY CHECK (octet_length(id)=32),
    feed text NOT NULL,
    receipt_day date NOT NULL,
    received_at timestamptz NOT NULL,
    bytes integer NOT NULL CHECK (bytes>0),
    body jsonb NOT NULL,
    batch_id text REFERENCES odds_archive_batch(id)
);
CREATE INDEX odds_archive_unclaimed ON odds_archive_stage(receipt_day,feed,id) WHERE batch_id IS NULL;
CREATE INDEX odds_archive_batch_rows ON odds_archive_stage(batch_id,id) WHERE batch_id IS NOT NULL;
ALTER TABLE odds_archive_stage SET (autovacuum_vacuum_scale_factor=0.05);

CREATE TABLE odds_archive_usage (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    staged_bytes bigint NOT NULL DEFAULT 0 CHECK (staged_bytes>=0)
);
INSERT INTO odds_archive_usage DEFAULT VALUES;

CREATE TABLE odds_archive_feed_status (
    feed text PRIMARY KEY,
    staged bigint NOT NULL DEFAULT 0,
    verified bigint NOT NULL DEFAULT 0,
    verified_file_bytes bigint NOT NULL DEFAULT 0,
    last_staged_at timestamptz,
    last_verified_at timestamptz,
    last_verified_file text,
    skipped bigint NOT NULL DEFAULT 0,
    first_gap_at timestamptz,
    last_gap_at timestamptz,
    gap_reason text
);
