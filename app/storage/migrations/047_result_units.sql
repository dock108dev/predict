-- One replaceable independently sealed unit per parent occurrence/unit identity.
-- Selected read frames copy their evidence into the existing leased read packet;
-- replacing or pruning this working projection cannot revoke captured Originals.
CREATE TABLE current_result_unit (
    game_key text NOT NULL,
    unit_id text NOT NULL,
    captured_at timestamptz NOT NULL,
    calculated_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    generation_id text NOT NULL,
    facts jsonb NOT NULL,
    retained_bytes bigint GENERATED ALWAYS AS (octet_length(facts::text)) STORED,
    PRIMARY KEY (game_key,unit_id)
);
CREATE INDEX current_result_unit_age ON current_result_unit(published_at);
