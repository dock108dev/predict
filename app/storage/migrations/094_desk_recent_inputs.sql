-- Lead current comparison reads with the quote clock, before joining books
-- or reconstructing exact price and lifecycle evidence.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE INDEX desk_native_receipt_order ON current_offer_storage (received_order)
    WHERE native_book_id IS NOT NULL;
CREATE INDEX desk_aggregate_source_order ON current_offer_storage (source_order)
    WHERE native_book_id IS NULL;

CREATE INDEX desk_sgo_frame_receipt ON sgo_event_evidence (received_order) INCLUDE (event_id)
    WHERE kind = 'frame';
