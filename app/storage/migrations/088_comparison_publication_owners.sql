-- Comparison publications share one pointer owner. Result references retain
-- exact input and calculation bytes through the existing snapshot foreign key.
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '5s';
SELECT pg_advisory_xact_lock(901153);
SELECT pg_advisory_xact_lock(901154);
SELECT pg_advisory_xact_lock(903019);
LOCK TABLE comparison_snapshot_result, comparison_snapshot_head,
    comparison_live_head, comparison_live_component, coverage_latest, scanner_latest,
    comparison_snapshot_review, comparison_live_lease, comparison_live_member,
    comparison_live_read_fragment IN ACCESS EXCLUSIVE MODE;

CREATE TABLE comparison_publication (
    kind text NOT NULL,
    id text NOT NULL,
    result_id text REFERENCES comparison_snapshot_result(id),
    generation bigint,
    facts jsonb,
    captured_at text,
    revision text,
    scanner_runtime_id text,
    scanner_runtime_revision bigint,
    scanner_published_at timestamptz,
    PRIMARY KEY (kind,id),
    CHECK ((kind='scanner')=(scanner_runtime_id IS NOT NULL) AND
           (kind='scanner')=(scanner_runtime_revision IS NOT NULL) AND
           (kind='scanner')=(scanner_published_at IS NOT NULL)),
    CHECK (CASE kind
        WHEN 'manual' THEN id='' AND result_id IS NOT NULL AND generation IS NULL AND facts IS NULL
            AND captured_at IS NULL AND revision IS NULL
        WHEN 'live' THEN id='' AND generation IS NOT NULL AND facts IS NOT NULL
            AND captured_at IS NULL AND revision IS NULL
        WHEN 'component' THEN id<>'' AND result_id IS NOT NULL AND generation IS NULL AND facts IS NOT NULL
            AND captured_at IS NULL AND revision IS NULL
        WHEN 'coverage' THEN id='' AND result_id IS NULL AND generation IS NULL AND facts IS NOT NULL
            AND captured_at IS NOT NULL AND revision IS NOT NULL AND octet_length(facts::text)<=8388608
        WHEN 'scanner' THEN id='' AND result_id IS NULL AND generation IS NOT NULL AND facts IS NOT NULL
            AND captured_at IS NULL AND revision IS NOT NULL AND octet_length(facts::text)<=33554432
        ELSE false END)
);
CREATE INDEX comparison_publication_result ON comparison_publication(result_id) WHERE result_id IS NOT NULL;
ALTER TABLE comparison_publication SET (autovacuum_vacuum_scale_factor=0.01, autovacuum_vacuum_threshold=10,
    toast.autovacuum_vacuum_scale_factor=0.01, toast.autovacuum_vacuum_threshold=10);

CREATE TABLE comparison_result_reference (
    kind text NOT NULL,
    holder text NOT NULL,
    result_id text NOT NULL REFERENCES comparison_snapshot_result(id),
    position integer CHECK (position>0),
    expires_at timestamptz,
    parent_result_id text GENERATED ALWAYS AS (CASE WHEN kind='member' THEN holder END) STORED
        REFERENCES comparison_snapshot_result(id) ON DELETE CASCADE,
    PRIMARY KEY(kind,holder,result_id),
    CHECK (CASE kind
        WHEN 'review' THEN holder=result_id AND position IS NULL AND expires_at IS NULL
        WHEN 'lease' THEN holder<>'' AND position IS NULL AND expires_at IS NOT NULL
        WHEN 'member' THEN expires_at IS NULL
        ELSE false END)
);
CREATE UNIQUE INDEX comparison_reference_lease_id ON comparison_result_reference(holder) WHERE kind='lease';
CREATE UNIQUE INDEX comparison_reference_member_order ON comparison_result_reference(holder,position)
    WHERE kind='member' AND position IS NOT NULL;
CREATE INDEX comparison_reference_result ON comparison_result_reference(result_id);
CREATE INDEX comparison_reference_parent ON comparison_result_reference(parent_result_id) WHERE parent_result_id IS NOT NULL;
CREATE INDEX comparison_reference_expiring ON comparison_result_reference(expires_at) WHERE kind='lease';

INSERT INTO comparison_publication (kind,id,result_id)
    SELECT 'manual','',result_id FROM comparison_snapshot_head;
INSERT INTO comparison_publication (kind,id,result_id,generation,facts)
    SELECT 'live','',result_id,generation,facts FROM comparison_live_head;
INSERT INTO comparison_publication (kind,id,result_id,facts)
    SELECT 'component',id,result_id,facts FROM comparison_live_component;
INSERT INTO comparison_publication (kind,id,facts,captured_at,revision)
    SELECT 'coverage','',facts,captured_at,revision FROM coverage_latest;
INSERT INTO comparison_publication (kind,id,generation,facts,revision,scanner_runtime_id,
                                    scanner_runtime_revision,scanner_published_at)
    SELECT 'scanner','',publication,payload,dependency_revision,runtime_id,runtime_revision,published_at
    FROM scanner_latest;
INSERT INTO comparison_result_reference (kind,holder,result_id)
    SELECT 'review',result_id,result_id FROM comparison_snapshot_review;
INSERT INTO comparison_result_reference (kind,holder,result_id,expires_at)
    SELECT 'lease',id,result_id,expires_at FROM comparison_live_lease;
INSERT INTO comparison_result_reference (kind,holder,result_id,position)
    SELECT 'member',result_id,member_id,position FROM comparison_live_member;

-- A compact projection shares the immutable result's key and lifetime. Check
-- rewrite runway first since PostgreSQL may copy the updated result tuple.
DO $$
DECLARE copy_bytes bigint;
BEGIN
    SELECT COALESCE(sum(octet_length(r.result)+octet_length(f.content)+octet_length(f.summary::text)+256),0)
        INTO copy_bytes FROM comparison_live_read_fragment f JOIN comparison_snapshot_result r ON r.id=f.member_id;
    IF pg_database_size(current_database())+2*copy_bytes+67108864>=2147483648 THEN
        RAISE EXCEPTION 'comparison_fragment_migration_headroom';
    END IF;
END $$;
ALTER TABLE comparison_snapshot_result
    ADD COLUMN read_summary jsonb,
    ADD COLUMN read_fragment bytea,
    ADD CONSTRAINT comparison_result_complete_fragment CHECK ((read_summary IS NULL)=(read_fragment IS NULL));
CREATE TEMP TABLE comparison_fragment_evidence_before ON COMMIT DROP AS
    SELECT r.id,sha256(r.result) AS result_hash,sha256(s.inputs) AS input_hash
    FROM comparison_snapshot_result r JOIN comparison_snapshot s ON s.id=r.snapshot_id
    WHERE r.id IN (SELECT member_id FROM comparison_live_read_fragment
                   UNION SELECT result_id FROM comparison_snapshot_review);
UPDATE comparison_snapshot_result r SET read_summary=f.summary,read_fragment=f.content
    FROM comparison_live_read_fragment f WHERE r.id=f.member_id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM comparison_live_read_fragment f LEFT JOIN comparison_snapshot_result r ON r.id=f.member_id
                WHERE (r.read_summary,r.read_fragment) IS DISTINCT FROM (f.summary,f.content))
       OR EXISTS (SELECT 1 FROM comparison_fragment_evidence_before b
                  LEFT JOIN comparison_snapshot_result r ON r.id=b.id
                  LEFT JOIN comparison_snapshot s ON s.id=r.snapshot_id
                  WHERE (sha256(r.result),sha256(s.inputs)) IS DISTINCT FROM (b.result_hash,b.input_hash))
       OR (SELECT count(*) FROM comparison_publication) <>
          ((SELECT count(*) FROM comparison_snapshot_head)+(SELECT count(*) FROM comparison_live_head)
          +(SELECT count(*) FROM comparison_live_component)+(SELECT count(*) FROM coverage_latest)
          +(SELECT count(*) FROM scanner_latest))
       OR (SELECT count(*) FROM comparison_result_reference) <>
          ((SELECT count(*) FROM comparison_snapshot_review)+(SELECT count(*) FROM comparison_live_lease)
          +(SELECT count(*) FROM comparison_live_member)) THEN
        RAISE EXCEPTION 'comparison_owner_migration_equivalence';
    END IF;
END $$;

DROP TABLE comparison_snapshot_head,comparison_live_head,comparison_live_component,coverage_latest,scanner_latest,
    comparison_snapshot_review,comparison_live_lease,comparison_live_member,comparison_live_read_fragment;
