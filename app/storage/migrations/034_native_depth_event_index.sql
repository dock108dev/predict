-- Component memory admission counts ask levels by event without a venue filter.
-- The venue-first primary key cannot serve that query efficiently.
CREATE INDEX IF NOT EXISTS current_native_depth_event_asks
    ON current_native_depth (event_id) WHERE side='asks';
