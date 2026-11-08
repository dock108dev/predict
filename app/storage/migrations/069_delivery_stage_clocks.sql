-- Bounded diagnostic facts; never price, quota or publication authority.
CREATE TABLE comparison_delivery_clock (
 league text NOT NULL,
 received_at timestamptz NOT NULL,
 first_recorded_capture_at timestamptz NOT NULL,
 last_capture_at timestamptz NOT NULL,
 capture_count integer NOT NULL,
 first_publication_write_at timestamptz,
 PRIMARY KEY(league,received_at)
);
