-- Bounded semantic witnesses and stage clocks, no provider response bodies.
ALTER TABLE pipeline_generation ADD COLUMN trace jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK(octet_length(trace::text)<=16384);
