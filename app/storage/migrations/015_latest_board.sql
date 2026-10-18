-- Replaceable compact ordinary Odds/EV/Arbs results, never report history.
CREATE TABLE latest_board_status (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 facts jsonb NOT NULL, updated_at text NOT NULL
);
CREATE TABLE latest_board (
 game_key text PRIMARY KEY,
 dependency_revision text NOT NULL,
 economic_revision text NOT NULL,
 calculated_at text NOT NULL,
 facts jsonb NOT NULL,
 CHECK(octet_length(facts::text)<=2097152)
);
ALTER TABLE latest_board SET (autovacuum_vacuum_scale_factor=0.05,autovacuum_vacuum_threshold=20);
