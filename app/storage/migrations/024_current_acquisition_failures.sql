-- Private opaque evidence. Never included in ordinary status or rendered as text.
CREATE TABLE current_acquisition_failure (
    id bigserial PRIMARY KEY,
    source text NOT NULL,
    received_at timestamptz NOT NULL,
    generation integer NOT NULL,
    stage text NOT NULL,
    disposition text NOT NULL,
    body_sha256 text NOT NULL,
    wire_bytes integer NOT NULL,
    body bytea NOT NULL
);
CREATE INDEX current_acquisition_failure_source ON current_acquisition_failure(source,id);
