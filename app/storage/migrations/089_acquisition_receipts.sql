-- Resumable traversal, aggregate observations, and rejected wire evidence
-- share one landing owner. Only a traversal page has a query parent.
SET LOCAL statement_timeout = '90s';
LOCK TABLE current_acquisition_query, current_acquisition_page,
    current_acquisition_failure, current_aggregate_receipt IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF pg_database_size(current_database()) + 67108864 +
       (SELECT sum(pg_total_relation_size(name::regclass)) FROM unnest(ARRAY[
           'current_acquisition_query','current_acquisition_page','current_acquisition_failure',
           'current_aggregate_receipt']) AS source(name)) >= 2147483648 THEN
        RAISE EXCEPTION 'acquisition_receipt_migration_headroom';
    END IF;
END $$;

CREATE SEQUENCE acquisition_failure_id;
CREATE TABLE acquisition_receipt (
    kind text NOT NULL,
    source text NOT NULL CHECK (source <> ''),
    scope text NOT NULL,
    event_id text NOT NULL DEFAULT '',
    position bigint NOT NULL DEFAULT -1,
    query_generation text,
    payload jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    received_at timestamptz,
    cycle_id text,
    receipt_sha256 text,
    disposition text,
    failure_generation integer,
    failure_stage text,
    wire_bytes integer,
    wire_body bytea,
    parent_kind text GENERATED ALWAYS AS (CASE WHEN kind='page' THEN 'query' END) STORED,
    parent_position bigint GENERATED ALWAYS AS (CASE WHEN kind='page' THEN -1 END) STORED,
    PRIMARY KEY (kind,source,scope,event_id,position),
    FOREIGN KEY (parent_kind,source,scope,event_id,parent_position)
        REFERENCES acquisition_receipt(kind,source,scope,event_id,position) ON DELETE CASCADE,
    CHECK (
        (kind='query' AND scope<>'' AND event_id='' AND position=-1
          AND query_generation IS NOT NULL AND payload IS NOT NULL AND started_at IS NOT NULL
          AND received_at IS NULL AND cycle_id IS NULL AND receipt_sha256 IS NULL AND disposition IS NULL)
        OR (kind='page' AND scope<>'' AND event_id='' AND position>=0
          AND query_generation IS NULL AND payload IS NOT NULL AND started_at IS NULL AND completed_at IS NULL
          AND received_at IS NULL AND cycle_id IS NULL AND receipt_sha256 IS NULL AND disposition IS NULL)
        OR (kind IN ('featured','alternate','census') AND scope<>'' AND position=-1
          AND query_generation IS NULL AND payload IS NOT NULL AND started_at IS NULL AND completed_at IS NULL
          AND received_at IS NOT NULL AND ((kind='alternate')=(event_id<>''))
          AND (kind='featured' OR (cycle_id IS NOT NULL AND receipt_sha256 IS NOT NULL))
          AND ((kind='alternate')=(disposition IS NOT NULL)))
        OR (kind='failure' AND scope='' AND event_id='' AND position>0
          AND query_generation IS NULL AND payload IS NULL AND started_at IS NULL AND completed_at IS NULL
          AND received_at IS NOT NULL AND cycle_id IS NULL AND receipt_sha256 IS NOT NULL AND disposition IS NOT NULL)
    ),
    CHECK (kind='failure' AND failure_generation IS NOT NULL AND failure_stage IS NOT NULL
            AND wire_bytes IS NOT NULL AND wire_body IS NOT NULL
        OR kind<>'failure' AND failure_generation IS NULL AND failure_stage IS NULL
            AND wire_bytes IS NULL AND wire_body IS NULL)
);
CREATE UNIQUE INDEX acquisition_receipt_failure_id ON acquisition_receipt(position) WHERE kind='failure';
CREATE INDEX acquisition_receipt_failures_by_source ON acquisition_receipt(source,position) WHERE kind='failure';
CREATE INDEX acquisition_receipt_query_parent ON acquisition_receipt(parent_kind,source,scope,event_id,parent_position)
    WHERE parent_kind IS NOT NULL;

INSERT INTO acquisition_receipt (kind,source,scope,query_generation,payload,started_at,completed_at)
    SELECT 'query',source,query_key,generation,request,started_at,completed_at FROM current_acquisition_query;
INSERT INTO acquisition_receipt (kind,source,scope,position,payload)
    SELECT 'page',source,query_key,position,receipt FROM current_acquisition_page;
INSERT INTO acquisition_receipt (kind,source,scope,position,received_at,receipt_sha256,disposition,
                                 failure_generation,failure_stage,wire_bytes,wire_body)
    SELECT 'failure',source,'',id,received_at,body_sha256,disposition,generation,stage,wire_bytes,body
    FROM current_acquisition_failure;
INSERT INTO acquisition_receipt (kind,source,scope,event_id,received_at,cycle_id,receipt_sha256,disposition,payload)
    SELECT kind,provider,sport,event_id,received_at,cycle_id,receipt_sha256,disposition,payload
    FROM current_aggregate_receipt;
SELECT setval('acquisition_failure_id',last_value,is_called) FROM current_acquisition_failure_id_seq;

ALTER TABLE current_acquisition_query RENAME TO acquisition_query_before_089;
ALTER TABLE current_acquisition_page RENAME TO acquisition_page_before_089;
ALTER TABLE current_acquisition_failure RENAME TO acquisition_failure_before_089;
ALTER TABLE current_aggregate_receipt RENAME TO aggregate_receipt_before_089;

CREATE VIEW current_acquisition_query AS
    SELECT source,scope AS query_key,query_generation AS generation,payload AS request,started_at,completed_at
    FROM acquisition_receipt WHERE kind='query';
CREATE VIEW current_acquisition_page AS
    SELECT source,scope AS query_key,position::integer, payload AS receipt
    FROM acquisition_receipt WHERE kind='page';
CREATE VIEW current_acquisition_failure AS
    SELECT position AS id,source,received_at,failure_generation AS generation,failure_stage AS stage,
        disposition,receipt_sha256 AS body_sha256,wire_bytes,wire_body AS body
    FROM acquisition_receipt WHERE kind='failure';
CREATE VIEW current_aggregate_receipt AS
    SELECT source AS provider,kind,scope AS sport,event_id,received_at,cycle_id,receipt_sha256,disposition,payload
    FROM acquisition_receipt WHERE kind IN ('featured','alternate','census');

DO $$
BEGIN
    IF EXISTS (SELECT * FROM acquisition_query_before_089 EXCEPT ALL SELECT * FROM current_acquisition_query)
       OR EXISTS (SELECT * FROM acquisition_page_before_089 EXCEPT ALL SELECT * FROM current_acquisition_page)
       OR EXISTS (SELECT * FROM acquisition_failure_before_089 EXCEPT ALL SELECT * FROM current_acquisition_failure)
       OR EXISTS (SELECT * FROM aggregate_receipt_before_089 EXCEPT ALL SELECT * FROM current_aggregate_receipt) THEN
        RAISE EXCEPTION 'acquisition_receipt_migration_equivalence';
    END IF;
END $$;

-- Rebind the existing flattened raw read before removing its original owner.
DO $$
DECLARE definition text := pg_get_viewdef('raw_aggregate_display'::regclass, false);
BEGIN
    EXECUTE 'CREATE OR REPLACE VIEW raw_aggregate_display AS ' ||
        replace(definition,'aggregate_receipt_before_089','current_aggregate_receipt');
END $$;
DROP TABLE acquisition_page_before_089,acquisition_query_before_089,
    acquisition_failure_before_089,aggregate_receipt_before_089;
