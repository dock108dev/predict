-- Complete featured + alternate games measured at 3.93 MB compact JSON.
-- JSONB text whitespace and exact selected inputs share this per-game budget.
-- Read-frame, complete-read and RSS guards remain independently enforced.
ALTER TABLE latest_board DROP CONSTRAINT latest_board_facts_check;
ALTER TABLE latest_board ADD CONSTRAINT latest_board_facts_check CHECK(octet_length(facts::text)<=6291456);
