"""Committed source health and authoritative replacement cursors."""

from psycopg.types.json import Jsonb


def source_status(execute, venue, state, at):
    execute('''INSERT INTO current_row_state (kind, identity, state, received_at)
        VALUES ('source',%s,%s,%s) ON CONFLICT (kind,identity) DO UPDATE
        SET state=excluded.state,received_at=excluded.received_at
        WHERE current_row_state.state<>excluded.state''', (venue, Jsonb(state), at))


def refresh_scopes(execute, values):
    execute('''INSERT INTO current_row_state (kind,identity,source_order,received_order)
        SELECT 'scope',* FROM unnest(%s::text[],%s::numeric[],%s::numeric[])
        ON CONFLICT (kind,identity) DO UPDATE
        SET source_order=excluded.source_order,received_order=excluded.received_order
        WHERE (current_row_state.source_order,current_row_state.received_order)
           IS DISTINCT FROM (excluded.source_order,excluded.received_order)''', tuple(map(list, zip(*values))))
