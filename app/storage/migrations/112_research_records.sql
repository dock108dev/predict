-- Research evidence is append-only and separate from personal decisions/fills.
CREATE TABLE public.research_record (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK(kind IN ('cohort','observation','capture','sporting','settlement','evaluation')),
    cohort_id text,
    case_key text,
    slot text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK(payload_bytes>0),
    payload jsonb NOT NULL
);
CREATE UNIQUE INDEX research_cohort_name ON public.research_record((payload->>'name')) WHERE kind='cohort';
CREATE UNIQUE INDEX research_capture_slot ON public.research_record(cohort_id,case_key,slot) WHERE kind='capture';
CREATE INDEX research_records_cohort ON public.research_record(cohort_id,kind,case_key,recorded_at,id);
CREATE FUNCTION research_record_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Store.immutable's retry updates the key to itself. All content and clocks
    -- must remain identical; no consumer can replace an earlier result.
    IF TG_OP='UPDATE' AND ROW(NEW.*) IS NOT DISTINCT FROM ROW(OLD.*) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'research_record_is_immutable';
END;
$$;
CREATE TRIGGER research_immutable BEFORE UPDATE OR DELETE ON public.research_record
    FOR EACH ROW EXECUTE FUNCTION research_record_immutable();
