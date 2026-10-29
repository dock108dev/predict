-- Complete 280-price publications measured at 2.44 MB before lower-threshold
-- sharing. Keep a per-game bound as well as the writer's total and RSS guards.
ALTER TABLE latest_board DROP CONSTRAINT latest_board_facts_check;
ALTER TABLE latest_board ADD CONSTRAINT latest_board_facts_check CHECK(octet_length(facts::text)<=4194304);
