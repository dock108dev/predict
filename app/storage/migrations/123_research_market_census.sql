-- A derived witness can be backfilled without rewriting any original checkpoint.
CREATE TABLE public.research_market_census (
    format_version text NOT NULL,
    checkpoint_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    evidence_revision text NOT NULL UNIQUE CHECK (length(evidence_revision)=64),
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK (payload_bytes>0),
    payload jsonb NOT NULL,
    PRIMARY KEY (format_version,checkpoint_id)
);
CREATE TRIGGER research_market_census_immutable BEFORE UPDATE OR DELETE ON public.research_market_census
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TABLE public.research_market_census_retry (
    format_version text NOT NULL,
    checkpoint_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    retry_after timestamptz NOT NULL,
    reason text NOT NULL,
    PRIMARY KEY(format_version,checkpoint_id)
);
CREATE INDEX ev_experiment_late_record_census ON public.ev_experiment_record(recorded_at DESC,id)
    WHERE kind='checkpoint' AND checkpoint='late';
