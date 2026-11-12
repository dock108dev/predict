-- Run against the existing project socket with psql -X -v ON_ERROR_STOP=1.
-- Counts describe retained provider observations; desk eligibility is separate.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';

SELECT transaction_timestamp() AS sampled_at,
       pg_database_size(current_database()) AS database_bytes;

WITH observations AS (
    SELECT facts->>'league' AS league,
           facts->>'phase' AS phase,
           bookmaker_id,
           facts->>'available' = 'true' AS available,
           received_order - source_order AS receipt_age_seconds,
           extract(epoch FROM transaction_timestamp()) - source_order AS source_age_seconds,
           source_order >= extract(epoch FROM (facts->>'starts_at')::timestamptz) AS post_start
    FROM current_sgo_reference
    WHERE expires_at > transaction_timestamp()
)
SELECT league, phase, bookmaker_id, count(*) AS retained,
       count(*) FILTER (WHERE available) AS available,
       count(*) FILTER (WHERE available AND receipt_age_seconds BETWEEN 0 AND 15)
           AS within_15s_at_receipt,
       count(*) FILTER (WHERE available AND post_start AND receipt_age_seconds >= 0)
           AS post_start_at_receipt,
       count(*) FILTER (WHERE available AND post_start AND receipt_age_seconds BETWEEN 0 AND 15)
           AS post_start_within_15s_at_receipt,
       count(*) FILTER (WHERE available AND receipt_age_seconds >= 0 AND source_age_seconds BETWEEN 0 AND 900)
           AS within_15m_at_read,
       count(*) FILTER (WHERE available AND post_start AND receipt_age_seconds >= 0 AND source_age_seconds BETWEEN 0 AND 15)
           AS post_start_within_15s_at_read
FROM observations
GROUP BY league, phase, bookmaker_id
ORDER BY league, phase, bookmaker_id;

-- These publication clocks belong to the same page receipt as the original
-- observations. A page's first published offer need not use every book fact.
SELECT to_regclass('public.current_sgo_delivery_clock') IS NOT NULL AS has_sgo_delivery_clock \gset
\if :has_sgo_delivery_clock
WITH observations AS (
    SELECT r.facts->>'league' AS league, r.facts->>'phase' AS phase,
           r.facts->>'available' = 'true' AS available,
           r.received_order - r.source_order AS source_to_receipt,
           extract(epoch FROM d.admitted_at) - r.received_order AS receipt_to_admission,
           extract(epoch FROM d.first_recorded_capture_at - d.admitted_at) AS admission_to_capture,
           extract(epoch FROM d.first_publication_write_at - d.admitted_at) AS admission_to_publication,
           extract(epoch FROM d.admitted_at) - r.source_order AS source_at_admission,
           extract(epoch FROM d.first_recorded_capture_at) - r.source_order AS source_at_capture,
           extract(epoch FROM d.first_publication_write_at) - r.source_order AS source_at_publication,
           r.source_order >= extract(epoch FROM (r.facts->>'starts_at')::timestamptz) AS post_start
    FROM current_sgo_reference r
    LEFT JOIN current_sgo_delivery_clock d
      ON d.league=r.facts->>'league' AND d.received_at=(r.facts->>'received_at')::timestamptz
    WHERE r.expires_at > transaction_timestamp()
      AND r.received_order >= extract(epoch FROM transaction_timestamp() - interval '1 hour')
)
SELECT league, phase, count(*) AS observations,
       count(*) FILTER (WHERE available) AS available,
       count(*) FILTER (WHERE available AND source_at_admission IS NOT NULL) AS with_admission_clock,
       count(*) FILTER (WHERE available AND source_at_capture IS NOT NULL) AS with_capture_clock,
       count(*) FILTER (WHERE available AND source_at_publication IS NOT NULL) AS with_publication_clock,
       count(*) FILTER (WHERE available AND phase='live' AND post_start AND source_to_receipt BETWEEN 0 AND 15) AS live_fresh_at_receipt,
       count(*) FILTER (WHERE available AND phase='live' AND post_start AND source_to_receipt BETWEEN 0 AND 15
                        AND receipt_to_admission >= 0
                        AND source_at_admission BETWEEN 0 AND 15) AS live_fresh_at_admission,
       count(*) FILTER (WHERE available AND phase='live' AND post_start AND source_to_receipt BETWEEN 0 AND 15
                        AND receipt_to_admission >= 0 AND admission_to_capture >= 0
                        AND source_at_capture BETWEEN 0 AND 15) AS live_fresh_at_page_capture,
       count(*) FILTER (WHERE available AND phase='live' AND post_start AND source_to_receipt BETWEEN 0 AND 15
                        AND receipt_to_admission >= 0 AND admission_to_publication >= 0
                        AND source_at_publication BETWEEN 0 AND 15) AS live_fresh_at_page_publication,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY source_to_receipt)
              FILTER (WHERE available AND source_to_receipt >= 0))::numeric, 3) AS p50_source_to_receipt_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY receipt_to_admission)
              FILTER (WHERE available AND receipt_to_admission >= 0))::numeric, 3) AS p50_receipt_to_admission_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY admission_to_capture)
              FILTER (WHERE available AND admission_to_capture >= 0))::numeric, 3) AS p50_admission_to_capture_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY admission_to_publication)
              FILTER (WHERE available AND admission_to_publication >= 0))::numeric, 3) AS p50_admission_to_publication_s
FROM observations
GROUP BY league, phase
ORDER BY league, phase;
\else
\echo SGO delivery-clock migration unavailable. Continuing with the retained history census.
\endif

SELECT kind, count(*) AS retained,
       coalesce(sum(payload_bytes), 0) AS payload_bytes,
       min(archived_at) AS oldest,
       max(archived_at) AS newest,
       count(*) FILTER (WHERE archived_at < transaction_timestamp() - interval '7 days') AS older_than_7d
FROM current_sgo_history
GROUP BY GROUPING SETS ((kind), ())
ORDER BY kind NULLS LAST;

SELECT recorded, skipped_capacity, skipped_runway, evicted_capacity,
       pg_total_relation_size('current_sgo_history') AS history_relation_bytes
FROM current_sgo_history_state
WHERE singleton;

ROLLBACK;
