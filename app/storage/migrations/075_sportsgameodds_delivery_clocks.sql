-- Diagnostic timestamps only. The source clock still controls price expiry.
CREATE TABLE current_sgo_delivery_clock (
    league text NOT NULL,
    received_at timestamptz NOT NULL,
    admitted_at timestamptz,
    first_recorded_capture_at timestamptz,
    last_capture_at timestamptz,
    capture_count integer NOT NULL,
    first_publication_write_at timestamptz,
    PRIMARY KEY (league, received_at)
);
