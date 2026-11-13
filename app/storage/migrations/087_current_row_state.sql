-- Epoch, source health, and replacement cursors share the current-row writer.
SELECT pg_advisory_xact_lock(901095);
LOCK TABLE current_row_epoch,current_source_status,current_refresh_scope IN ACCESS EXCLUSIVE MODE;
CREATE TABLE current_row_state (
    kind text NOT NULL,
    identity text NOT NULL,
    epoch text,
    state jsonb,
    received_at text,
    source_order numeric,
    received_order numeric,
    PRIMARY KEY (kind, identity),
    CHECK (
        (kind = 'epoch' AND identity = '' AND epoch IS NOT NULL AND state IS NULL
         AND received_at IS NULL AND source_order IS NULL AND received_order IS NULL)
        OR (kind = 'source' AND epoch IS NULL AND state IS NOT NULL AND received_at IS NOT NULL
            AND source_order IS NULL AND received_order IS NULL)
        OR (kind = 'scope' AND epoch IS NULL AND state IS NULL AND received_at IS NULL
            AND source_order IS NOT NULL AND received_order IS NOT NULL)
    )
);
CREATE INDEX current_row_state_scope_expiry ON current_row_state (received_order) WHERE kind = 'scope';
INSERT INTO current_row_state (kind, identity, epoch)
    SELECT 'epoch', '', epoch FROM current_row_epoch;
INSERT INTO current_row_state (kind, identity, state, received_at)
    SELECT 'source', venue, state, received_at FROM current_source_status;
INSERT INTO current_row_state (kind, identity, source_order, received_order)
    SELECT 'scope', scope, source_order, received_order FROM current_refresh_scope;
DO $$
BEGIN
    IF EXISTS (SELECT epoch FROM current_row_epoch EXCEPT ALL
        SELECT epoch FROM current_row_state WHERE kind='epoch')
       OR EXISTS (SELECT * FROM current_source_status EXCEPT ALL
        SELECT identity,state,received_at FROM current_row_state WHERE kind='source')
       OR EXISTS (SELECT * FROM current_refresh_scope EXCEPT ALL
        SELECT identity,source_order,received_order FROM current_row_state WHERE kind='scope') THEN
        RAISE EXCEPTION 'current_row_state_migration_equivalence';
    END IF;
END $$;
DROP TABLE current_row_epoch, current_source_status, current_refresh_scope;

CREATE VIEW current_row_epoch AS
    SELECT true AS singleton, epoch FROM current_row_state WHERE kind = 'epoch' WITH LOCAL CHECK OPTION;
CREATE VIEW current_source_status AS
    SELECT identity AS venue, state, received_at FROM current_row_state WHERE kind = 'source' WITH LOCAL CHECK OPTION;
CREATE VIEW current_refresh_scope AS
    SELECT identity AS scope, source_order, received_order FROM current_row_state WHERE kind = 'scope';
