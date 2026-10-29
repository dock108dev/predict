-- Replaceable acquisition evidence, independent of semantic/financial admission.
CREATE TABLE current_acquisition_query (
    source text NOT NULL,
    query_key text NOT NULL,
    generation text NOT NULL,
    request jsonb NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (source, query_key)
);
CREATE TABLE current_acquisition_page (
    source text NOT NULL,
    query_key text NOT NULL,
    position integer NOT NULL,
    receipt jsonb NOT NULL,
    PRIMARY KEY (source, query_key, position),
    FOREIGN KEY (source, query_key) REFERENCES current_acquisition_query
        ON DELETE CASCADE
);
CREATE TABLE current_acquisition_image (
    source text NOT NULL,
    event_id text NOT NULL,
    market_id text NOT NULL,
    received_at timestamptz NOT NULL,
    disposition text NOT NULL,
    image jsonb NOT NULL,
    PRIMARY KEY (source, event_id, market_id)
);
CREATE INDEX current_acquisition_image_receipt ON current_acquisition_image(received_at);
