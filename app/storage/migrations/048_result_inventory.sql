-- Discovery accounting must survive an all-deferred calculation turn.
CREATE TABLE current_result_inventory (
    game_key text PRIMARY KEY,
    discovered_at timestamptz NOT NULL,
    revision text NOT NULL,
    events jsonb NOT NULL,
    dependencies jsonb NOT NULL,
    units jsonb NOT NULL,
    CHECK (jsonb_typeof(units)='array')
);
CREATE SEQUENCE current_result_visit;
CREATE TABLE current_result_work (
    game_key text NOT NULL REFERENCES current_result_inventory(game_key) ON DELETE CASCADE,
    unit_id text NOT NULL,
    inventory_revision text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    visit_order bigint NOT NULL DEFAULT nextval('current_result_visit'),
    visits bigint NOT NULL DEFAULT 0,
    last_visit timestamptz,
    reconciled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    reason text NOT NULL DEFAULT 'discovered',
    PRIMARY KEY (game_key,unit_id)
);
CREATE INDEX current_result_work_order ON current_result_work(game_key,active,visit_order);

-- One captured list retains only its requested board. All selected_frame
-- evidence and generation/dependency identities remain exact and complete.
CREATE FUNCTION current_result_read_facts(value jsonb, view_name text) RETURNS jsonb
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN value ? 'result_units' THEN
        (value-'boards'-'result_units') || jsonb_build_object('result_units',COALESCE((
            SELECT jsonb_object_agg(key, jsonb_set(child,'{facts,boards}',
                jsonb_build_object(view_name, child#>ARRAY['facts','boards',view_name])))
            FROM jsonb_each(value->'result_units') AS u(key,child)), '{}'::jsonb))
        ELSE value-'boards' END
$$;
