-- Projection lifetime is reconciled by its publisher. Keep the independent
-- replaceable table out of source-reset/TRUNCATE dependency chains.
ALTER TABLE latest_dashboard DROP CONSTRAINT latest_dashboard_game_key_fkey;
