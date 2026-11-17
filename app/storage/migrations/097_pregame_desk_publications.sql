-- Independently replaceable selected-unit publications share ordinary member retention.
ALTER TABLE comparison_snapshot_result ADD COLUMN desk_index jsonb;
ALTER TABLE comparison_snapshot_result ADD COLUMN desk_fragment bytea;

CREATE TABLE pregame_unit_board (
    unit_cents integer PRIMARY KEY CHECK (unit_cents BETWEEN 1 AND 100000000),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    root_id text REFERENCES comparison_snapshot_result(id) ON DELETE SET NULL,
    board_id text,
    policy_id text,
    projection bytea CHECK (octet_length(projection) <= 8388608),
    error text
);
CREATE INDEX pregame_unit_board_root ON pregame_unit_board(root_id) WHERE root_id IS NOT NULL;

CREATE TABLE pregame_unit_member (
    unit_cents integer NOT NULL REFERENCES pregame_unit_board(unit_cents) ON DELETE CASCADE,
    member_id text NOT NULL REFERENCES comparison_snapshot_result(id) ON DELETE CASCADE,
    policy_id text NOT NULL,
    valuation bytea NOT NULL CHECK (octet_length(valuation) <= 8388608),
    PRIMARY KEY(unit_cents,member_id,policy_id)
);
CREATE INDEX pregame_unit_member_result ON pregame_unit_member(member_id);
