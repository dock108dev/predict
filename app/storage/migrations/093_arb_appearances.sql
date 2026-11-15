-- Small server-side history independent of replacement publication retention.
CREATE TABLE arb_appearance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pair_id text NOT NULL,
    appeared_at timestamptz NOT NULL,
    disappeared_at timestamptz CHECK (disappeared_at >= appeared_at),
    generation bigint NOT NULL CHECK (generation > 0),
    facts jsonb NOT NULL CHECK (jsonb_typeof(facts) = 'object')
);
CREATE UNIQUE INDEX arb_appearance_active ON arb_appearance (pair_id) WHERE disappeared_at IS NULL;
CREATE INDEX arb_appearance_recent ON arb_appearance (appeared_at DESC, id DESC);
CREATE INDEX arb_appearance_closed ON arb_appearance (disappeared_at, id) WHERE disappeared_at IS NOT NULL;
