-- Event frames and independently timed native catalog witnesses share an
-- event evidence owner. History counters use a separate typed row in it.
LOCK TABLE current_sgo_event_frame,current_sgo_native_catalog,current_sgo_history_state
    IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF pg_database_size(current_database()) + 67108864 +
       (SELECT sum(pg_total_relation_size(name::regclass)) FROM unnest(ARRAY[
           'current_sgo_event_frame','current_sgo_native_catalog','current_sgo_history_state']) AS source(name))
           >= 2147483648 THEN
        RAISE EXCEPTION 'sgo_event_evidence_migration_headroom';
    END IF;
END $$;
CREATE TABLE sgo_event_evidence (
    kind text NOT NULL,
    event_id text NOT NULL,
    received_order numeric,
    observed_at timestamptz,
    expires_at timestamptz,
    revision text,
    payload_bytes integer,
    facts jsonb,
    recorded bigint,
    skipped_capacity bigint,
    skipped_runway bigint,
    evicted_capacity bigint,
    PRIMARY KEY (kind,event_id),
    CHECK (
        (kind='frame' AND received_order IS NOT NULL AND payload_bytes IS NOT NULL
         AND observed_at IS NULL AND revision IS NULL)
        OR (kind='catalog' AND observed_at IS NOT NULL AND revision IS NOT NULL
            AND received_order IS NULL AND payload_bytes IS NULL)
        OR (kind='history_state' AND event_id='' AND received_order IS NULL AND observed_at IS NULL
            AND revision IS NULL AND payload_bytes IS NULL)
    ),
    CHECK (kind='history_state' AND expires_at IS NULL AND facts IS NULL AND recorded IS NOT NULL
            AND skipped_capacity IS NOT NULL AND skipped_runway IS NOT NULL AND evicted_capacity IS NOT NULL
        OR kind<>'history_state' AND expires_at IS NOT NULL AND facts IS NOT NULL AND recorded IS NULL
            AND skipped_capacity IS NULL AND skipped_runway IS NULL AND evicted_capacity IS NULL)
);
CREATE INDEX sgo_event_evidence_expiry ON sgo_event_evidence (kind,expires_at);
INSERT INTO sgo_event_evidence (kind,event_id,received_order,expires_at,payload_bytes,facts)
    SELECT 'frame',event_id,received_order,expires_at,payload_bytes,facts FROM current_sgo_event_frame;
INSERT INTO sgo_event_evidence (kind,event_id,observed_at,expires_at,revision,facts)
    SELECT 'catalog',event_id,observed_at,expires_at,revision,facts FROM current_sgo_native_catalog;
INSERT INTO sgo_event_evidence (kind,event_id,recorded,skipped_capacity,skipped_runway,evicted_capacity)
    SELECT 'history_state','',recorded,skipped_capacity,skipped_runway,evicted_capacity FROM current_sgo_history_state;

DO $$
BEGIN
    IF EXISTS (SELECT * FROM current_sgo_event_frame EXCEPT ALL
        SELECT event_id,received_order,expires_at,payload_bytes,facts FROM sgo_event_evidence WHERE kind='frame')
       OR EXISTS (SELECT * FROM current_sgo_native_catalog EXCEPT ALL
        SELECT event_id,observed_at,expires_at,revision,facts FROM sgo_event_evidence WHERE kind='catalog')
       OR EXISTS (SELECT * FROM current_sgo_history_state EXCEPT ALL
        SELECT true,recorded,skipped_capacity,skipped_runway,evicted_capacity FROM sgo_event_evidence WHERE kind='history_state') THEN
        RAISE EXCEPTION 'sgo_event_evidence_migration_equivalence';
    END IF;
END $$;
DROP TABLE current_sgo_event_frame,current_sgo_native_catalog,current_sgo_history_state;
CREATE VIEW current_sgo_event_frame AS
    SELECT event_id,received_order,expires_at,payload_bytes,facts FROM sgo_event_evidence WHERE kind='frame';
CREATE VIEW current_sgo_native_catalog AS
    SELECT event_id,observed_at,expires_at,revision,facts FROM sgo_event_evidence WHERE kind='catalog';
CREATE VIEW current_sgo_history_state AS
    SELECT true AS singleton,recorded,skipped_capacity,skipped_runway,evicted_capacity
    FROM sgo_event_evidence WHERE kind='history_state';
