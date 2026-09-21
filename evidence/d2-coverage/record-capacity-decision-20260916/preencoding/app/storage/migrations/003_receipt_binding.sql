-- Bind the complete receipt set to a calculation identity, including empty sets.
ALTER TABLE calculation ADD COLUMN receipt_ids jsonb NOT NULL DEFAULT '[]';
UPDATE calculation c SET receipt_ids=coalesce((SELECT jsonb_agg(r.receipt_id ORDER BY r.receipt_id)
 FROM calculation_receipt r WHERE r.session_id=c.session_id AND r.calculation_id=c.id),'[]'::jsonb);
