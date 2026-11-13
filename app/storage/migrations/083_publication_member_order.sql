-- The relation owns membership for new publications. Old roots have their
-- original manifest order in the encoded result and remain readable.
ALTER TABLE comparison_live_member ADD COLUMN position integer CHECK (position > 0);
CREATE UNIQUE INDEX comparison_live_member_position
    ON comparison_live_member (result_id,position) WHERE position IS NOT NULL;
