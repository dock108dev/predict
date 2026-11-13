-- One diagnostic clock per provider, league and receipt.
CREATE TABLE delivery_clock (
    provider text NOT NULL CHECK (provider IN ('the_odds_api','sportsgameodds')),
    league text NOT NULL,
    received_at timestamptz NOT NULL,
    admitted_at timestamptz,
    first_recorded_capture_at timestamptz,
    last_capture_at timestamptz,
    capture_count integer NOT NULL CHECK (capture_count >= 0),
    first_publication_write_at timestamptz,
    first_live_sportsbook_write_at timestamptz,
    PRIMARY KEY (provider, league, received_at)
);
INSERT INTO delivery_clock
    SELECT 'the_odds_api',league,received_at,NULL,first_recorded_capture_at,last_capture_at,
           capture_count,first_publication_write_at,NULL FROM comparison_delivery_clock
    UNION ALL
    SELECT 'sportsgameodds',league,received_at,admitted_at,first_recorded_capture_at,last_capture_at,
           capture_count,first_publication_write_at,first_live_sportsbook_write_at FROM current_sgo_delivery_clock;
DROP TABLE comparison_delivery_clock,current_sgo_delivery_clock;
-- Historical diagnostic SQL remains readable through a projection of the owner.
CREATE VIEW current_sgo_delivery_clock AS
    SELECT league,received_at,admitted_at,first_recorded_capture_at,last_capture_at,
           capture_count,first_publication_write_at,first_live_sportsbook_write_at
    FROM delivery_clock WHERE provider='sportsgameodds';
