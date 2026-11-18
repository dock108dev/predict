-- Rebuild generated EV under the owner's two-distinct-trusted-book rule.
-- Raw prices, original receipts and protected accounting remain unchanged.
INSERT INTO current_pregame_work(provider,native_event_id)
 SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
 WHERE e.scheduled_start::timestamptz>clock_timestamp()
 ON CONFLICT(provider,native_event_id) DO UPDATE
 SET revision=current_pregame_work.revision+1,error=NULL;
