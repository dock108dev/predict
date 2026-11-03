-- Replaceable dashboard projection, atomically owned by the board publisher.
CREATE TABLE latest_dashboard (
    game_key text PRIMARY KEY REFERENCES latest_board(game_key) ON DELETE CASCADE,
    dependency_revision text NOT NULL,
    economic_revision text NOT NULL,
    calculated_at text,
    facts jsonb NOT NULL
);
