-- Independent latest Monitor/Live inputs. Original quote clocks stay unchanged.
-- These working cohorts are bounded by kickoff; immutable history is archived.
CREATE SCHEMA pregame_monitor;
CREATE SCHEMA pregame_live;
CREATE SCHEMA pregame_combined;
DO $$
DECLARE s text; t text; key text;
BEGIN
  FOREACH t IN ARRAY ARRAY['current_event','current_contract','current_offer_storage',
    'current_sgo_reference','sgo_line_presence','current_pregame_calculation','current_pregame_price'] LOOP
    key := CASE WHEN t IN ('current_offer_storage','current_pregame_calculation','current_pregame_price') THEN 'contract_id'
                WHEN t='sgo_line_presence' THEN 'quote_id' ELSE 'id' END;
    FOREACH s IN ARRAY ARRAY['pregame_monitor','pregame_live','pregame_combined'] LOOP
      EXECUTE format('CREATE TABLE %I.%I AS SELECT p.*, NULL::timestamptz AS cohort_observed_at FROM public.%I p WITH NO DATA',s,t,t);
      EXECUTE format('CREATE UNIQUE INDEX ON %I.%I (%I)',s,t,key);
      IF t IN ('current_contract','current_sgo_reference','sgo_line_presence') THEN
        EXECUTE format('CREATE INDEX ON %I.%I (event_id)',s,t);
      END IF;
      IF t IN ('current_pregame_calculation','current_pregame_price') THEN
        EXECUTE format('CREATE INDEX ON %I.%I (game_key,start_at)',s,t);
      END IF;
    END LOOP;
  END LOOP;
  FOREACH s IN ARRAY ARRAY['pregame_monitor','pregame_live','pregame_combined'] LOOP
    -- Global pending work must not hide an already committed other-mode snapshot.
    EXECUTE format('CREATE TABLE %I.current_pregame_work (LIKE public.current_pregame_work)',s);
    EXECUTE format('CREATE TABLE %I.current_pregame_revision (LIKE public.current_pregame_revision INCLUDING ALL)',s);
    EXECUTE format('INSERT INTO %I.current_pregame_revision VALUES(true,0,NULL)',s);
  END LOOP;
END $$;

-- A fee edit invalidates both retained cohorts immediately, even before the
-- next source collection. Source polling of one mode never expires the other.
CREATE FUNCTION pregame_cohort_fee_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; s text;
BEGIN
  IF TG_OP='UPDATE' AND
    (NEW.state->'last_verified',NEW.state->'review_required',NEW.state->'pricing_rules') IS NOT DISTINCT FROM
    (OLD.state->'last_verified',OLD.state->'review_required',OLD.state->'pricing_rules') THEN RETURN NEW; END IF;
  IF TG_OP='DELETE' THEN v:=split_part(OLD.venue,':',1); ELSE v:=split_part(NEW.venue,':',1); END IF;
  FOREACH s IN ARRAY ARRAY['pregame_monitor','pregame_live','pregame_combined'] LOOP
    EXECUTE format('UPDATE %I.current_pregame_calculation SET valid_until=LEAST(valid_until,clock_timestamp()) WHERE venue=$1',s) USING v;
    EXECUTE format('UPDATE %I.current_pregame_price SET valid_until=LEAST(valid_until,clock_timestamp()) WHERE payload->>''venue''=$1',s) USING v;
    EXECUTE format('UPDATE %I.current_pregame_revision SET revision=revision+1,committed_at=clock_timestamp() WHERE singleton',s);
  END LOOP;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER pregame_cohort_fee AFTER INSERT OR UPDATE OR DELETE ON public_fee_schedule
  FOR EACH ROW EXECUTE FUNCTION pregame_cohort_fee_changed();
