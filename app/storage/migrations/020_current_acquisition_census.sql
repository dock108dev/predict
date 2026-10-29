CREATE TABLE current_acquisition_market (
    source text NOT NULL,
    event_id text NOT NULL,
    market_id text NOT NULL,
    sport text NOT NULL,
    family text NOT NULL,
    generation text NOT NULL,
    observed_at timestamptz NOT NULL,
    withdrawn boolean NOT NULL DEFAULT false,
    disposition text NOT NULL,
    metadata jsonb NOT NULL,
    PRIMARY KEY (source,event_id,market_id)
);
CREATE INDEX current_acquisition_market_cell ON current_acquisition_market(source,sport,family,withdrawn);
CREATE TABLE current_acquisition_aggregate (
    sport text PRIMARY KEY,
    received_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
