-- Keep exact retained aggregate responses in one scope-keyed owner.
SET LOCAL statement_timeout = '60s';
LOCK TABLE current_acquisition_aggregate, current_acquisition_alternate,
    current_acquisition_event_census, raw_aggregate_display IN ACCESS EXCLUSIVE MODE;

CREATE TABLE current_aggregate_receipt (
    provider text NOT NULL CHECK (provider <> ''),
    kind text NOT NULL CHECK (kind IN ('featured','alternate','census')),
    sport text NOT NULL,
    event_id text NOT NULL DEFAULT '',
    received_at timestamptz NOT NULL,
    cycle_id text,
    receipt_sha256 text,
    disposition text,
    payload jsonb NOT NULL,
    PRIMARY KEY (provider,kind,sport,event_id),
    CHECK ((kind='alternate') = (event_id <> '')),
    CHECK (kind='featured' OR (cycle_id IS NOT NULL AND receipt_sha256 IS NOT NULL)),
    CHECK ((kind='alternate') = (disposition IS NOT NULL))
);

INSERT INTO current_aggregate_receipt (provider,kind,sport,received_at,payload)
SELECT 'the_odds_api','featured',sport,received_at,payload FROM current_acquisition_aggregate;
INSERT INTO current_aggregate_receipt
    (provider,kind,sport,event_id,received_at,cycle_id,receipt_sha256,disposition,payload)
SELECT 'the_odds_api','alternate',sport,event_id,received_at,cycle_id,receipt_sha256,disposition,payload
FROM current_acquisition_alternate;
INSERT INTO current_aggregate_receipt (provider,kind,sport,received_at,cycle_id,receipt_sha256,payload)
SELECT 'the_odds_api','census',sport,received_at,cycle_id,receipt_sha256,payload FROM current_acquisition_event_census;

ALTER TABLE current_acquisition_aggregate RENAME TO aggregate_featured_before_084;
ALTER TABLE current_acquisition_alternate RENAME TO aggregate_alternate_before_084;
ALTER TABLE current_acquisition_event_census RENAME TO aggregate_census_before_084;
ALTER TABLE raw_aggregate_display RENAME TO aggregate_display_before_084;

CREATE VIEW current_acquisition_aggregate AS
    SELECT sport,received_at,payload FROM current_aggregate_receipt WHERE provider='the_odds_api' AND kind='featured';
CREATE VIEW current_acquisition_alternate AS
    SELECT sport,event_id,received_at,cycle_id,receipt_sha256,disposition,payload
    FROM current_aggregate_receipt WHERE provider='the_odds_api' AND kind='alternate';
CREATE VIEW current_acquisition_event_census AS
    SELECT sport,cycle_id,received_at,receipt_sha256,payload
    FROM current_aggregate_receipt WHERE provider='the_odds_api' AND kind='census';

CREATE VIEW raw_aggregate_display AS
SELECT DISTINCT ON (r.kind,r.sport,e.event->>'id',b.book->>'key',m.market->>'key')
    r.kind,r.sport,e.event->>'id' AS event_id,b.book->>'key' AS venue,
    m.market->>'key' AS market_id,r.received_at,
    concat_ws(' vs ',e.event->>'away_team',e.event->>'home_team') AS title,
    CASE m.market->>'key' WHEN 'h2h' THEN 'moneyline'
      WHEN 'spreads' THEN 'spread' WHEN 'alternate_spreads' THEN 'spread'
      WHEN 'totals' THEN 'total' WHEN 'alternate_totals' THEN 'total' ELSE 'unknown' END AS family,
    COALESCE(m.market->>'last_update',b.book->>'last_update') AS source_at,
    COALESCE(m.market->'outcomes','[]') AS outcomes
FROM current_aggregate_receipt r
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN r.kind='alternate' THEN jsonb_build_array(r.payload)
         WHEN jsonb_typeof(r.payload->'events')='array' THEN r.payload->'events'
         ELSE '[]' END) WITH ORDINALITY AS e(event,position)
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(e.event->'bookmakers')='array' THEN e.event->'bookmakers' ELSE '[]' END
) WITH ORDINALITY AS b(book,position)
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(b.book->'markets')='array' THEN b.book->'markets' ELSE '[]' END
) WITH ORDINALITY AS m(market,position)
WHERE r.provider='the_odds_api' AND r.kind IN ('featured','alternate')
  AND b.book->>'key' IN ('novig','prophetx','pinnacle') AND e.event->>'id' IS NOT NULL
ORDER BY r.kind,r.sport,e.event->>'id',b.book->>'key',m.market->>'key',
    r.received_at DESC,r.event_id,e.position,b.position,m.position;

DO $$
BEGIN
    IF EXISTS (SELECT * FROM aggregate_featured_before_084 EXCEPT ALL SELECT * FROM current_acquisition_aggregate)
        OR EXISTS (SELECT * FROM current_acquisition_aggregate EXCEPT ALL SELECT * FROM aggregate_featured_before_084)
        OR EXISTS (SELECT * FROM aggregate_alternate_before_084 EXCEPT ALL SELECT * FROM current_acquisition_alternate)
        OR EXISTS (SELECT * FROM current_acquisition_alternate EXCEPT ALL SELECT * FROM aggregate_alternate_before_084)
        OR EXISTS (SELECT * FROM aggregate_census_before_084 EXCEPT ALL SELECT * FROM current_acquisition_event_census)
        OR EXISTS (SELECT * FROM current_acquisition_event_census EXCEPT ALL SELECT * FROM aggregate_census_before_084)
    THEN RAISE EXCEPTION 'aggregate_receipt_migration_equivalence';
    END IF;
END;
$$;

DROP TABLE aggregate_featured_before_084,aggregate_alternate_before_084,aggregate_census_before_084;
DROP VIEW current_acquisition_aggregate,current_acquisition_alternate,current_acquisition_event_census;
DROP TABLE aggregate_display_before_084;
DROP FUNCTION raw_aggregate_refresh(),raw_aggregate_delete();
