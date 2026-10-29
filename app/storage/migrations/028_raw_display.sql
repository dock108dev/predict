-- Acquire the final lock mode first; avoid lock upgrades against live writers.
LOCK TABLE current_acquisition_image IN ACCESS EXCLUSIVE MODE;
-- Compact aggregate lookup rows; full native books remain solely in acquisition.
CREATE TABLE raw_aggregate_display (
 kind text NOT NULL, sport text NOT NULL, event_id text NOT NULL,
 venue text NOT NULL, market_id text NOT NULL, received_at timestamptz NOT NULL,
 title text NOT NULL, family text NOT NULL, source_at text, outcomes jsonb NOT NULL,
 PRIMARY KEY(kind,sport,event_id,venue,market_id)
);
CREATE INDEX raw_aggregate_filters ON raw_aggregate_display(sport,venue,family,event_id);
CREATE INDEX raw_native_event ON current_acquisition_image(event_id,source,market_id);
CREATE FUNCTION raw_aggregate_refresh() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE events jsonb;
BEGIN
 IF TG_TABLE_NAME='current_acquisition_aggregate' THEN
  DELETE FROM raw_aggregate_display WHERE kind='featured' AND sport=NEW.sport;
  events=NEW.payload->'events';
 ELSE
  DELETE FROM raw_aggregate_display WHERE kind='alternate' AND sport=NEW.sport AND event_id=NEW.event_id;
  events=jsonb_build_array(NEW.payload);
 END IF;
 INSERT INTO raw_aggregate_display
 SELECT CASE WHEN TG_TABLE_NAME='current_acquisition_aggregate' THEN 'featured' ELSE 'alternate' END,
 NEW.sport, e->>'id', b->>'key', m->>'key', NEW.received_at,
 concat_ws(' vs ',e->>'away_team',e->>'home_team'),
 CASE m->>'key' WHEN 'h2h' THEN 'moneyline' WHEN 'spreads' THEN 'spread'
 WHEN 'alternate_spreads' THEN 'spread' WHEN 'totals' THEN 'total' WHEN 'alternate_totals' THEN 'total' ELSE 'unknown' END,
 COALESCE(m->>'last_update',b->>'last_update'),COALESCE(m->'outcomes','[]')
 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(events)='array' THEN events ELSE '[]' END) e
 CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(e->'bookmakers')='array' THEN e->'bookmakers' ELSE '[]' END) b
 CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(b->'markets')='array' THEN b->'markets' ELSE '[]' END) m
 WHERE b->>'key' IN ('novig','prophetx','pinnacle') AND e->>'id' IS NOT NULL
 ON CONFLICT(kind,sport,event_id,venue,market_id) DO UPDATE SET outcomes=EXCLUDED.outcomes,source_at=EXCLUDED.source_at;
 RETURN NEW;
END $$;
CREATE TRIGGER raw_featured AFTER INSERT OR UPDATE ON current_acquisition_aggregate FOR EACH ROW EXECUTE FUNCTION raw_aggregate_refresh();
CREATE TRIGGER raw_alternate AFTER INSERT OR UPDATE ON current_acquisition_alternate FOR EACH ROW EXECUTE FUNCTION raw_aggregate_refresh();
UPDATE current_acquisition_aggregate SET received_at=received_at;
UPDATE current_acquisition_alternate SET received_at=received_at;
-- Persistence is distinct from receipt. Existing rows have unknown write time.
ALTER TABLE current_acquisition_image ADD COLUMN persisted_at timestamptz;
CREATE FUNCTION raw_persistence_clock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
  NEW.persisted_at=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER raw_persistence BEFORE INSERT OR UPDATE ON current_acquisition_image FOR EACH ROW EXECUTE FUNCTION raw_persistence_clock();
CREATE FUNCTION raw_aggregate_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='current_acquisition_aggregate' THEN
  DELETE FROM raw_aggregate_display WHERE kind='featured' AND sport=OLD.sport;
 ELSE
  DELETE FROM raw_aggregate_display WHERE kind='alternate' AND sport=OLD.sport AND event_id=OLD.event_id;
 END IF;
 RETURN OLD;
END $$;
CREATE TRIGGER raw_featured_delete AFTER DELETE ON current_acquisition_aggregate FOR EACH ROW EXECUTE FUNCTION raw_aggregate_delete();
CREATE TRIGGER raw_alternate_delete AFTER DELETE ON current_acquisition_alternate FOR EACH ROW EXECUTE FUNCTION raw_aggregate_delete();
